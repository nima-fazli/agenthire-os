from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.core.text_chunking import (
    CHUNKER_VERSION,
    ChunkingFailure,
    chunk_text,
    text_digest,
)
from app.models.document_chunk import DocumentChunk, DocumentChunkSet
from app.repositories.candidate_document import CandidateDocumentRepository
from app.repositories.document_chunk import DocumentChunkRepository
from app.repositories.document_extraction import DocumentExtractionRepository
from app.services.candidate_document import CandidateDocumentService


class DocumentChunkService:
    def __init__(
        self,
        session: AsyncSession,
        documents: CandidateDocumentService,
        settings: Settings,
    ) -> None:
        self._session = session
        self._documents = documents
        self._settings = settings
        self._document_repository = CandidateDocumentRepository(session)
        self._extractions = DocumentExtractionRepository(session)
        self._repository = DocumentChunkRepository(session)

    async def build_for_user(
        self,
        document_id: UUID,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        user_id: UUID,
    ) -> tuple[DocumentChunkSet, bool]:
        scope = {
            "organization_id": organization_id,
            "candidate_id": candidate_id,
            "document_id": document_id,
        }
        await self._documents.get_for_user(
            document_id,
            organization_id=organization_id,
            candidate_id=candidate_id,
            user_id=user_id,
        )
        policy = None
        try:
            document = await self._document_repository.get_for_candidate(
                **scope, for_update=True
            )
            if document is None:
                raise NotFoundError(
                    code="DOCUMENT_NOT_FOUND", message="Document was not found."
                )
            extraction = await self._extractions.get_for_candidate(
                **scope, for_update=True
            )
            if extraction is None:
                raise NotFoundError(
                    code="EXTRACTION_NOT_FOUND", message="Extraction was not requested."
                )
            if extraction.status != "succeeded":
                raise ConflictError(
                    code="EXTRACTION_FAILED"
                    if extraction.status == "failed"
                    else "EXTRACTION_NOT_READY",
                    message="Successful extraction is required before chunking.",
                )
            text = extraction.text
            settings = self._settings
            policy = {
                "source_text_sha256": text_digest(text),
                "chunker_version": CHUNKER_VERSION,
                "max_chars": settings.chunk_max_chars,
                "overlap_chars": settings.chunk_overlap_chars,
            }
            existing = await self._repository.get_policy(**scope, **policy)
            if existing is not None:
                await self._session.commit()
                return existing, False
            chunks = await run_in_threadpool(
                chunk_text,
                text,
                max_chars=settings.chunk_max_chars,
                overlap_chars=settings.chunk_overlap_chars,
                max_count=settings.chunk_max_count,
            )
            chunk_set = await self._repository.create(
                DocumentChunkSet(
                    document_id=document_id,
                    source_document_sha256=document.sha256,
                    source_text_sha256=policy["source_text_sha256"],
                    source_char_count=len(text),
                    page_count=extraction.page_count,
                    chunker_version=CHUNKER_VERSION,
                    chunk_max_chars=settings.chunk_max_chars,
                    chunk_overlap_chars=settings.chunk_overlap_chars,
                    chunk_count=len(chunks),
                ),
                chunks,
            )
            await self._session.commit()
            return chunk_set, True
        except ChunkingFailure as error:
            await self._session.rollback()
            raise ConflictError(
                code=error.code,
                message="Document could not be chunked within the configured limits.",
            ) from error
        except IntegrityError:
            await self._session.rollback()
            await self._documents.get_for_user(
                document_id,
                organization_id=organization_id,
                candidate_id=candidate_id,
                user_id=user_id,
            )
            existing = (
                await self._repository.get_policy(**scope, **policy) if policy else None
            )
            if existing is not None:
                return existing, False
            raise
        except BaseException:
            await self._session.rollback()
            raise

    async def get_for_user(
        self,
        document_id: UUID,
        chunk_set_id: UUID,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        user_id: UUID,
    ) -> DocumentChunkSet:
        await self._documents.get_for_user(
            document_id,
            organization_id=organization_id,
            candidate_id=candidate_id,
            user_id=user_id,
        )
        chunk_set = await self._repository.get(
            organization_id=organization_id,
            candidate_id=candidate_id,
            document_id=document_id,
            chunk_set_id=chunk_set_id,
        )
        if chunk_set is None:
            raise NotFoundError(
                code="CHUNK_SET_NOT_FOUND", message="Chunk set was not found."
            )
        return chunk_set

    async def list_for_user(
        self,
        document_id: UUID,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        user_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[DocumentChunkSet], int]:
        await self._documents.get_for_user(
            document_id,
            organization_id=organization_id,
            candidate_id=candidate_id,
            user_id=user_id,
        )
        return await self._repository.list_sets(
            organization_id=organization_id,
            candidate_id=candidate_id,
            document_id=document_id,
            limit=limit,
            offset=offset,
        )

    async def chunks_for_user(
        self,
        document_id: UUID,
        chunk_set_id: UUID,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        user_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[DocumentChunkSet, list[DocumentChunk]]:
        chunk_set = await self.get_for_user(
            document_id,
            chunk_set_id,
            organization_id=organization_id,
            candidate_id=candidate_id,
            user_id=user_id,
        )
        chunks = await self._repository.list_chunks(
            organization_id=organization_id,
            candidate_id=candidate_id,
            document_id=document_id,
            chunk_set_id=chunk_set_id,
            limit=limit,
            offset=offset,
        )
        return chunk_set, chunks
