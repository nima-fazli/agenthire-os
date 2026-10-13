from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.semantic_embeddings import (
    ENCODING_VERSION,
    MODEL_TAG,
    ModelIdentity,
    SourceChunk,
)
from app.models.candidate_document import CandidateDocument
from app.models.document_chunk import DocumentChunk, DocumentChunkSet
from app.models.document_embeddings import DocumentEmbedding, DocumentEmbeddingJob
from app.models.document_extraction import DocumentExtraction


@dataclass(frozen=True)
class EmbeddingTask:
    id: UUID
    chunk_set_id: UUID
    model_digest: str
    chunk_count: int
    lease_token: UUID


class DocumentEmbeddingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def current_source():
        latest = aliased(DocumentChunkSet)
        latest_id = (
            select(latest.id).where(latest.document_id == CandidateDocument.id)
            .order_by(latest.created_at.desc(), latest.id.desc()).limit(1)
            .correlate(CandidateDocument).scalar_subquery()
        )
        return exists(
            select(DocumentChunkSet.id)
            .join(DocumentExtraction, DocumentExtraction.document_id == DocumentChunkSet.document_id)
            .join(CandidateDocument, CandidateDocument.id == DocumentChunkSet.document_id)
            .where(
                DocumentChunkSet.id == DocumentEmbeddingJob.chunk_set_id,
                DocumentChunkSet.id == latest_id,
                CandidateDocument.status == "ready",
                DocumentExtraction.status == "succeeded",
                DocumentChunkSet.source_document_sha256 == CandidateDocument.sha256,
                DocumentChunkSet.source_text_sha256 == DocumentEmbeddingJob.source_text_sha256,
                DocumentChunkSet.chunk_count == DocumentEmbeddingJob.chunk_count,
            )
        )

    async def latest_source(self, *, organization_id: UUID, candidate_id: UUID, document_id: UUID):
        statement = (
            select(DocumentChunkSet)
            .join(DocumentExtraction, DocumentExtraction.document_id == DocumentChunkSet.document_id)
            .join(CandidateDocument, CandidateDocument.id == DocumentChunkSet.document_id)
            .where(
                CandidateDocument.id == document_id,
                CandidateDocument.organization_id == organization_id,
                CandidateDocument.candidate_id == candidate_id,
                CandidateDocument.status == "ready",
                DocumentExtraction.status == "succeeded",
                DocumentChunkSet.source_document_sha256 == CandidateDocument.sha256,
            )
            .order_by(DocumentChunkSet.created_at.desc(), DocumentChunkSet.id.desc())
            .limit(1).with_for_update(of=CandidateDocument)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def for_space(self, chunk_set_id: UUID, identity: ModelIdentity):
        statement = select(DocumentEmbeddingJob).where(
            DocumentEmbeddingJob.chunk_set_id == chunk_set_id,
            DocumentEmbeddingJob.model_digest == identity.digest,
            DocumentEmbeddingJob.encoding_version == ENCODING_VERSION,
        ).with_for_update(of=DocumentEmbeddingJob).execution_options(populate_existing=True)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def create(self, source: DocumentChunkSet, identity: ModelIdentity):
        job = DocumentEmbeddingJob(
            chunk_set_id=source.id, model_tag=MODEL_TAG, model_digest=identity.digest,
            encoding_version=ENCODING_VERSION, source_text_sha256=source.source_text_sha256,
            chunk_count=source.chunk_count, status="queued", attempts=0,
        )
        self._session.add(job)
        await self._session.flush()
        await self._session.refresh(job)
        return job

    async def requeue(self, job: DocumentEmbeddingJob):
        job.status = "queued"
        job.failure_code = None
        job.completed_at = None
        await self._session.flush()
        await self._session.refresh(job)
        return job

    async def get_scoped(self, job_id: UUID, *, organization_id: UUID, candidate_id: UUID, document_id: UUID):
        statement = (
            select(DocumentEmbeddingJob).join(DocumentChunkSet)
            .join(CandidateDocument, CandidateDocument.id == DocumentChunkSet.document_id)
            .where(
                DocumentEmbeddingJob.id == job_id,
                CandidateDocument.id == document_id,
                CandidateDocument.organization_id == organization_id,
                CandidateDocument.candidate_id == candidate_id,
                CandidateDocument.status == "ready",
            )
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def claim(self, *, max_attempts: int, lease_seconds: int, job_id: UUID | None = None):
        scope = () if job_id is None else (DocumentEmbeddingJob.id == job_id,)
        available = or_(
            DocumentEmbeddingJob.status == "queued",
            and_(DocumentEmbeddingJob.status == "running", DocumentEmbeddingJob.lease_expires_at <= func.clock_timestamp()),
        )
        for condition, code in (
            (~self.current_source(), "EMBEDDING_SOURCE_OBSOLETE"),
            (DocumentEmbeddingJob.attempts >= max_attempts, "EMBEDDING_RETRY_LIMIT"),
        ):
            await self._session.execute(
                update(DocumentEmbeddingJob).where(*scope, available, condition).values(
                    status="failed", failure_code=code, completed_at=func.clock_timestamp(),
                    lease_token=None, lease_expires_at=None,
                ).execution_options(synchronize_session=False)
            )
        result = await self._session.execute(
            select(DocumentEmbeddingJob, func.clock_timestamp()).where(
                *scope, available, self.current_source(), DocumentEmbeddingJob.attempts < max_attempts,
            ).order_by(DocumentEmbeddingJob.created_at, DocumentEmbeddingJob.id)
            .limit(1).with_for_update(skip_locked=True, of=DocumentEmbeddingJob)
            .execution_options(populate_existing=True)
        )
        row = result.one_or_none()
        if row is None:
            return None
        job, now = row
        job.status = "running"
        job.attempts += 1
        job.lease_token = uuid4()
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        await self._session.flush()
        return EmbeddingTask(job.id, job.chunk_set_id, job.model_digest, job.chunk_count, job.lease_token)

    def owned(self, task: EmbeddingTask):
        return (
            DocumentEmbeddingJob.id == task.id,
            DocumentEmbeddingJob.status == "running",
            DocumentEmbeddingJob.lease_token == task.lease_token,
            DocumentEmbeddingJob.lease_expires_at > func.clock_timestamp(),
            self.current_source(),
        )

    async def chunks(self, task: EmbeddingTask) -> tuple[SourceChunk, ...]:
        statement = select(DocumentChunk.position, DocumentChunk.text, DocumentChunk.sha256).where(
            DocumentChunk.chunk_set_id == task.chunk_set_id,
            exists(select(DocumentEmbeddingJob.id).where(*self.owned(task))),
        ).order_by(DocumentChunk.position).limit(1001)
        rows = (await self._session.execute(statement)).all()
        return tuple(SourceChunk(*row) for row in rows)

    async def renew(self, task: EmbeddingTask, lease_seconds: int) -> bool:
        result = await self._session.execute(
            update(DocumentEmbeddingJob).where(*self.owned(task)).values(
                lease_expires_at=func.clock_timestamp() + timedelta(seconds=lease_seconds)
            ).execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    async def finish(self, task: EmbeddingTask, chunks: tuple[SourceChunk, ...], vectors, failure_code: str | None) -> bool:
        result = await self._session.execute(
            update(DocumentEmbeddingJob).where(*self.owned(task)).values(
                status="failed" if failure_code else "succeeded",
                failure_code=failure_code, completed_at=func.clock_timestamp(),
                lease_token=None, lease_expires_at=None,
            ).execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            return False
        if not failure_code:
            self._session.add_all([
                DocumentEmbedding(job_id=task.id, chunk_set_id=task.chunk_set_id,
                                  position=chunk.position, chunk_sha256=chunk.sha256, embedding=vector)
                for chunk, vector in zip(chunks, vectors, strict=True)
            ])
            await self._session.flush()
        return True
