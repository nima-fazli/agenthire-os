import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.local_embeddings import EmbeddingEncoder
from app.core.semantic_embeddings import (
    MAX_CHUNKS,
    EmbeddingFailure,
    ModelIdentity,
    normalized_vector,
    validate_chunks,
)
from app.repositories.document_embeddings import DocumentEmbeddingRepository
from app.schemas.document_embeddings import EmbeddingJobRead, EmbeddingRequest
from app.services.candidate_document import CandidateDocumentService

logger = logging.getLogger("agenthire.embeddings")


class DocumentEmbeddingService:
    def __init__(self, session: AsyncSession, documents: CandidateDocumentService,
                 encoder: EmbeddingEncoder, settings: Settings) -> None:
        self._session = session
        self._documents = documents
        self._encoder = encoder
        self._settings = settings
        self._repository = DocumentEmbeddingRepository(session)

    async def request(self, document_id: UUID, data: EmbeddingRequest, *, organization_id: UUID,
                      candidate_id: UUID, user_id: UUID) -> tuple[EmbeddingJobRead, bool]:
        scope = {"organization_id": organization_id, "candidate_id": candidate_id, "document_id": document_id}
        try:
            await self._documents.get_for_user(document_id, organization_id=organization_id,
                                               candidate_id=candidate_id, user_id=user_id)
            if not self._settings.semantic_enabled:
                raise AppError(code="SEMANTIC_DISABLED", message="Local semantic processing is disabled.", status_code=503)
            identity = await self._encoder.identity()
            source = await self._repository.latest_source(**scope)
            if source is None:
                raise ConflictError(code="DOCUMENT_CHUNKS_NOT_READY", message="Build source chunks before requesting embeddings.")
            if not 1 <= source.chunk_count <= MAX_CHUNKS:
                raise ConflictError(code="EMBEDDING_SOURCE_LIMIT", message="This source exceeds the local embedding chunk limit.")
            job = await self._repository.for_space(source.id, identity)
            created = job is None
            if created:
                job = await self._repository.create(source, identity)
            elif data.retry and job.status == "failed":
                if job.attempts >= self._settings.embedding_max_attempts:
                    raise ConflictError(code="EMBEDDING_RETRY_LIMIT", message="Embedding attempt limit was reached.")
                job = await self._repository.requeue(job)
            result = EmbeddingJobRead.model_validate(job)
            await self._session.commit()
            return result, created
        except EmbeddingFailure as error:
            await self._session.rollback()
            raise AppError(code=error.code, message="Local embedding model is unavailable or incompatible.", status_code=503) from error
        except BaseException:
            await self._session.rollback()
            raise

    async def get(self, document_id: UUID, job_id: UUID, *, organization_id: UUID,
                  candidate_id: UUID, user_id: UUID) -> EmbeddingJobRead:
        await self._documents.get_for_user(document_id, organization_id=organization_id,
                                           candidate_id=candidate_id, user_id=user_id)
        job = await self._repository.get_scoped(job_id, organization_id=organization_id,
                                                candidate_id=candidate_id, document_id=document_id)
        if job is None:
            raise NotFoundError(code="EMBEDDING_JOB_NOT_FOUND", message="Embedding job was not found.")
        return EmbeddingJobRead.model_validate(job)


class EmbeddingProcessor:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], encoder: EmbeddingEncoder,
                 settings: Settings) -> None:
        self._sessions = sessions
        self._encoder = encoder
        self._settings = settings

    async def run_one(self, *, job_id: UUID | None = None) -> bool:
        async with self._sessions() as session:
            try:
                task = await DocumentEmbeddingRepository(session).claim(
                    max_attempts=self._settings.embedding_max_attempts,
                    lease_seconds=self._settings.embedding_lease_seconds,
                    job_id=job_id,
                )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        if task is None:
            return False
        chunks, vectors, failure = (), [], None
        try:
            identity = ModelIdentity(task.model_digest)
            async with self._sessions() as session:
                chunks = await DocumentEmbeddingRepository(session).chunks(task)
            validate_chunks(chunks, task.chunk_count)
            size = self._settings.embedding_batch_size
            for start in range(0, len(chunks), size):
                batch = chunks[start:start + size]
                result = await self._encoder.encode(tuple(chunk.text for chunk in batch), identity)
                if len(result) != len(batch):
                    raise EmbeddingFailure("EMBEDDING_VECTOR_INVALID")
                vectors.extend(normalized_vector(value) for value in result)
                async with self._sessions() as session:
                    try:
                        renewed = await DocumentEmbeddingRepository(session).renew(task, self._settings.embedding_lease_seconds)
                        await session.commit()
                    except BaseException:
                        await session.rollback()
                        raise
                if not renewed:
                    logger.info("embedding_lease_lost job_id=%s", task.id)
                    return True
        except EmbeddingFailure as error:
            failure = error.code
        except Exception:
            logger.exception("embedding_processing_error")
            failure = "EMBEDDING_INTERNAL_ERROR"
        async with self._sessions() as session:
            try:
                accepted = await DocumentEmbeddingRepository(session).finish(task, chunks, vectors, failure)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        logger.info("embedding_result job_id=%s accepted=%s", task.id, accepted)
        return True
