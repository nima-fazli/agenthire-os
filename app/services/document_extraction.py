import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.document_storage import DocumentStorage, DocumentStorageError
from app.core.errors import ConflictError, NotFoundError
from app.core.pdf_extraction import ExtractionFailure, PdfExtractor
from app.models.document_extraction import DocumentExtraction
from app.repositories.candidate_document import CandidateDocumentRepository
from app.repositories.document_extraction import DocumentExtractionRepository
from app.schemas.document_extraction import ExtractionRequest
from app.services.candidate_document import CandidateDocumentService

logger = logging.getLogger("agenthire.extraction")


class DocumentExtractionService:
    def __init__(
        self,
        session: AsyncSession,
        documents: CandidateDocumentService,
        *,
        max_attempts: int,
    ) -> None:
        self._session = session
        self._documents = documents
        self._document_repository = CandidateDocumentRepository(session)
        self._repository = DocumentExtractionRepository(session)
        self._max_attempts = max_attempts

    async def request_for_user(
        self,
        document_id: UUID,
        data: ExtractionRequest,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        user_id: UUID,
    ) -> DocumentExtraction:
        scope = {"organization_id": organization_id, "candidate_id": candidate_id}
        await self._documents.get_for_user(document_id, **scope, user_id=user_id)
        try:
            document = await self._document_repository.get_for_candidate(
                **scope, document_id=document_id, for_update=True
            )
            if document is None:
                raise NotFoundError(
                    code="DOCUMENT_NOT_FOUND", message="Document was not found."
                )
            extraction = await self._repository.get_for_candidate(
                **scope, document_id=document_id, for_update=True
            )
            if extraction is None:
                extraction = await self._repository.create(document_id)
            elif data.retry and extraction.status == "failed":
                if extraction.attempts >= self._max_attempts:
                    raise ConflictError(
                        code="EXTRACTION_RETRY_LIMIT",
                        message="Extraction attempt limit was reached.",
                    )
                extraction = await self._repository.requeue(extraction)
            await self._session.commit()
            return extraction
        except IntegrityError:
            await self._session.rollback()
            await self._documents.get_for_user(document_id, **scope, user_id=user_id)
            existing = await self._repository.get_for_candidate(
                **scope, document_id=document_id
            )
            if existing is not None:
                return existing
            raise
        except BaseException:
            await self._session.rollback()
            raise

    async def get_for_user(
        self,
        document_id: UUID,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        user_id: UUID,
    ) -> DocumentExtraction:
        await self._documents.get_for_user(
            document_id,
            organization_id=organization_id,
            candidate_id=candidate_id,
            user_id=user_id,
        )
        extraction = await self._repository.get_for_candidate(
            document_id=document_id,
            organization_id=organization_id,
            candidate_id=candidate_id,
        )
        if extraction is None:
            raise NotFoundError(
                code="EXTRACTION_NOT_FOUND", message="Extraction was not requested."
            )
        return extraction

    async def text_for_user(
        self,
        document_id: UUID,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        user_id: UUID,
    ) -> DocumentExtraction:
        extraction = await self.get_for_user(
            document_id,
            organization_id=organization_id,
            candidate_id=candidate_id,
            user_id=user_id,
        )
        if extraction.status != "succeeded":
            raise ConflictError(
                code="EXTRACTION_FAILED"
                if extraction.status == "failed"
                else "EXTRACTION_NOT_READY",
                message="Extracted text is unavailable.",
                details={
                    "status": extraction.status,
                    "failure_code": extraction.failure_code,
                },
            )
        return extraction


class ExtractionProcessor:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        storage: DocumentStorage,
        extractor: PdfExtractor,
        settings: Settings,
    ) -> None:
        self._sessions = sessions
        self._storage = storage
        self._extractor = extractor
        self._settings = settings

    async def run_one(self) -> bool:
        async with self._sessions() as session:
            try:
                task = await DocumentExtractionRepository(session).claim_next(
                    max_attempts=self._settings.extraction_max_attempts,
                    lease_seconds=self._settings.extraction_lease_seconds,
                )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        if task is None:
            return False
        result = None
        failure_code = None
        try:
            handle = await self._storage.open(
                task.storage_key, expected_size=task.size_bytes
            )
            with handle:
                result = await self._extractor.extract(
                    handle, expected_sha256=task.sha256
                )
        except ExtractionFailure as error:
            failure_code = error.code
        except DocumentStorageError:
            failure_code = "DOCUMENT_STORAGE_UNAVAILABLE"
        except Exception:
            logger.exception("document_extraction_parser_error")
            failure_code = "EXTRACTION_INTERNAL_ERROR"
        async with self._sessions() as session:
            try:
                accepted = await DocumentExtractionRepository(session).finish_if_owned(
                    task, result=result, failure_code=failure_code
                )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        logger.info(
            "document_extraction_result document_id=%s accepted=%s",
            task.document_id,
            accepted,
        )
        return True
