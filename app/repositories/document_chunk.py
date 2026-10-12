from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text_chunking import TextChunk
from app.models.candidate_document import CandidateDocument
from app.models.document_chunk import DocumentChunk, DocumentChunkSet
from app.models.document_extraction import DocumentExtraction


class DocumentChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _sets(*, organization_id: UUID, candidate_id: UUID, document_id: UUID):
        return (
            select(DocumentChunkSet)
            .join(DocumentExtraction)
            .join(CandidateDocument)
            .where(
                CandidateDocument.organization_id == organization_id,
                CandidateDocument.candidate_id == candidate_id,
                CandidateDocument.id == document_id,
                CandidateDocument.status == "ready",
                DocumentExtraction.status == "succeeded",
            )
        )

    async def get_policy(
        self,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        document_id: UUID,
        source_text_sha256: str,
        chunker_version: str,
        max_chars: int,
        overlap_chars: int,
    ) -> DocumentChunkSet | None:
        statement = self._sets(
            organization_id=organization_id,
            candidate_id=candidate_id,
            document_id=document_id,
        ).where(
            DocumentChunkSet.source_text_sha256 == source_text_sha256,
            DocumentChunkSet.chunker_version == chunker_version,
            DocumentChunkSet.chunk_max_chars == max_chars,
            DocumentChunkSet.chunk_overlap_chars == overlap_chars,
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def create(
        self, chunk_set: DocumentChunkSet, chunks: list[TextChunk]
    ) -> DocumentChunkSet:
        if not chunks or len(chunks) != chunk_set.chunk_count:
            raise ValueError("Chunk count must match the complete chunk set.")
        self._session.add(chunk_set)
        await self._session.flush()
        for start in range(0, len(chunks), 250):
            await self._session.execute(
                insert(DocumentChunk),
                [
                    {
                        "chunk_set_id": chunk_set.id,
                        "position": chunk.position,
                        "start_offset": chunk.start_offset,
                        "end_offset": chunk.end_offset,
                        "text": chunk.text,
                        "sha256": chunk.sha256,
                    }
                    for chunk in chunks[start : start + 250]
                ],
            )
        await self._session.refresh(chunk_set)
        return chunk_set

    async def get(
        self,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        document_id: UUID,
        chunk_set_id: UUID,
    ) -> DocumentChunkSet | None:
        statement = self._sets(
            organization_id=organization_id,
            candidate_id=candidate_id,
            document_id=document_id,
        ).where(DocumentChunkSet.id == chunk_set_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def list_sets(
        self,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        document_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[DocumentChunkSet], int]:
        base = self._sets(
            organization_id=organization_id,
            candidate_id=candidate_id,
            document_id=document_id,
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(
                DocumentChunkSet.created_at.desc(), DocumentChunkSet.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total

    async def list_chunks(
        self,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        document_id: UUID,
        chunk_set_id: UUID,
        limit: int,
        offset: int,
    ) -> list[DocumentChunk]:
        statement = (
            select(DocumentChunk)
            .join(DocumentChunkSet)
            .join(DocumentExtraction)
            .join(CandidateDocument)
            .where(
                DocumentChunk.chunk_set_id == chunk_set_id,
                CandidateDocument.organization_id == organization_id,
                CandidateDocument.candidate_id == candidate_id,
                CandidateDocument.id == document_id,
                CandidateDocument.status == "ready",
                DocumentExtraction.status == "succeeded",
            )
            .order_by(DocumentChunk.position)
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(statement)).scalars().all())
