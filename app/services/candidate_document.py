import asyncio
import logging
from collections.abc import AsyncIterator
from typing import BinaryIO
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.document_storage import (
    DocumentStorage,
    DocumentStorageError,
    upload_error,
)
from app.core.errors import AppError, ConflictError, NotFoundError
from app.models.candidate_document import CandidateDocument
from app.repositories.candidate import CandidateRepository
from app.repositories.candidate_document import CandidateDocumentRepository
from app.repositories.organization_membership import OrganizationMembershipRepository
from app.schemas.candidate_document import DocumentUpload

logger = logging.getLogger("agenthire.documents")


class CandidateDocumentService:
    def __init__(
        self,
        session: AsyncSession,
        storage: DocumentStorage,
        *,
        max_bytes: int,
        upload_timeout_seconds: int = 60,
    ) -> None:
        self._session = session
        self._storage = storage
        self._max_bytes = max_bytes
        self._upload_timeout_seconds = upload_timeout_seconds
        self._repository = CandidateDocumentRepository(session)
        self._candidates = CandidateRepository(session)
        self._memberships = OrganizationMembershipRepository(session)

    async def _require_candidate(
        self, organization_id: UUID, candidate_id: UUID, user_id: UUID
    ) -> None:
        membership = await self._memberships.get_by_user_and_organization(
            organization_id=organization_id, user_id=user_id
        )
        if membership is None:
            raise NotFoundError(
                code="ORGANIZATION_NOT_FOUND", message="Organization was not found."
            )
        candidate = await self._candidates.get_for_organization(
            organization_id=organization_id, candidate_id=candidate_id
        )
        if candidate is None:
            raise NotFoundError(
                code="CANDIDATE_NOT_FOUND", message="Candidate was not found."
            )

    @staticmethod
    def _storage_error() -> AppError:
        return AppError(
            code="DOCUMENT_STORAGE_UNAVAILABLE",
            message="Document storage is unavailable.",
            status_code=503,
        )

    @staticmethod
    def _duplicate_error(document: CandidateDocument) -> ConflictError:
        deleting = document.status == "deleting"
        return ConflictError(
            code="DOCUMENT_DELETION_PENDING" if deleting else "DOCUMENT_ALREADY_EXISTS",
            message="Complete document deletion before uploading again."
            if deleting
            else "This candidate already has this document.",
            details={"document_id": str(document.id)},
        )

    async def _discard(self, storage_key: str) -> None:
        try:
            await self._storage.delete(storage_key)
        except DocumentStorageError:
            logger.exception("document_upload_cleanup_failed")

    async def _abort_upload(
        self,
        storage_key: str,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        document_id: UUID | None,
    ) -> None:
        try:
            await self._session.rollback()
            if document_id is not None:
                persisted = await self._repository.get_for_candidate(
                    organization_id=organization_id,
                    candidate_id=candidate_id,
                    document_id=document_id,
                    ready_only=False,
                )
                if persisted is not None:
                    return
        except Exception:
            logger.exception("document_upload_outcome_unknown")
            return
        await self._discard(storage_key)

    async def upload(
        self,
        data: DocumentUpload,
        chunks: AsyncIterator[bytes],
        *,
        organization_id: UUID,
        candidate_id: UUID,
        user_id: UUID,
        content_type: str,
        content_length: str | None,
    ) -> CandidateDocument:
        await self._require_candidate(organization_id, candidate_id, user_id)
        if content_type.split(";", 1)[0].strip().lower() != "application/pdf":
            raise upload_error(
                "UNSUPPORTED_DOCUMENT_TYPE", "Only application/pdf is supported.", 415
            )
        if content_length is not None:
            if not content_length.isascii() or not content_length.isdecimal():
                raise upload_error(
                    "INVALID_CONTENT_LENGTH",
                    "Content-Length must be non-negative.",
                    400,
                )
            normalized_length = content_length.lstrip("0") or "0"
            if len(normalized_length) > 10 or int(normalized_length) > self._max_bytes:
                raise upload_error(
                    "DOCUMENT_TOO_LARGE", "Document exceeds the size limit.", 413
                )
        try:
            async with asyncio.timeout(self._upload_timeout_seconds):
                stored = await self._storage.save_pdf(chunks, max_bytes=self._max_bytes)
        except TimeoutError as error:
            raise upload_error(
                "DOCUMENT_UPLOAD_TIMEOUT", "Document upload timed out.", 408
            ) from error
        except DocumentStorageError as error:
            raise self._storage_error() from error
        scope = {"organization_id": organization_id, "candidate_id": candidate_id}
        document_id = None
        try:
            existing = await self._repository.get_by_digest(
                **scope, sha256=stored.sha256
            )
            if existing is not None:
                raise self._duplicate_error(existing)
            document = await self._repository.create(
                **scope,
                uploaded_by_user_id=user_id,
                filename=data.filename,
                content_type="application/pdf",
                size_bytes=stored.size_bytes,
                sha256=stored.sha256,
                storage_key=stored.storage_key,
                status="ready",
            )
            document_id = document.id
            await self._session.commit()
            return document
        except IntegrityError:
            await self._session.rollback()
            await self._discard(stored.storage_key)
            existing = await self._repository.get_by_digest(
                **scope, sha256=stored.sha256
            )
            if existing is not None:
                raise self._duplicate_error(existing) from None
            raise
        except BaseException:
            await self._abort_upload(
                stored.storage_key, **scope, document_id=document_id
            )
            raise

    async def list_for_user(
        self,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        user_id: UUID,
        limit: int,
        offset: int,
    ) -> list[CandidateDocument]:
        await self._require_candidate(organization_id, candidate_id, user_id)
        return await self._repository.list_for_candidate(
            organization_id=organization_id,
            candidate_id=candidate_id,
            limit=limit,
            offset=offset,
        )

    async def get_for_user(
        self,
        document_id: UUID,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        user_id: UUID,
    ) -> CandidateDocument:
        await self._require_candidate(organization_id, candidate_id, user_id)
        document = await self._repository.get_for_candidate(
            organization_id=organization_id,
            candidate_id=candidate_id,
            document_id=document_id,
        )
        if document is None:
            raise NotFoundError(
                code="DOCUMENT_NOT_FOUND", message="Document was not found."
            )
        return document

    async def download_for_user(
        self,
        document_id: UUID,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        user_id: UUID,
    ) -> tuple[CandidateDocument, BinaryIO]:
        await self._require_candidate(organization_id, candidate_id, user_id)
        handle = None
        try:
            document = await self._repository.get_for_candidate(
                organization_id=organization_id,
                candidate_id=candidate_id,
                document_id=document_id,
                for_update=True,
            )
            if document is None:
                raise NotFoundError(
                    code="DOCUMENT_NOT_FOUND", message="Document was not found."
                )
            handle = await self._storage.open(
                document.storage_key, expected_size=document.size_bytes
            )
            await self._session.commit()
            return document, handle
        except BaseException as error:
            if handle is not None:
                handle.close()
            await self._session.rollback()
            if isinstance(error, DocumentStorageError):
                raise self._storage_error() from error
            raise

    async def delete_for_user(
        self,
        document_id: UUID,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        user_id: UUID,
    ) -> None:
        await self._require_candidate(organization_id, candidate_id, user_id)
        scope = {
            "organization_id": organization_id,
            "candidate_id": candidate_id,
            "document_id": document_id,
        }
        try:
            document = await self._repository.get_for_candidate(
                **scope, ready_only=False, for_update=True
            )
            if document is None:
                await self._session.commit()
                return
            await self._repository.mark_deleting(document)
            await self._session.commit()
            await self._storage.delete(document.storage_key)
            await self._repository.delete_for_candidate(**scope)
            await self._session.commit()
        except BaseException as error:
            await self._session.rollback()
            if isinstance(error, DocumentStorageError):
                raise self._storage_error() from error
            raise
