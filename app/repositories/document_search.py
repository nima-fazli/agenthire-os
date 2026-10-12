from uuid import UUID

from sqlalchemy import and_, exists, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.text_search import search_query, search_vector
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.document_chunk import DocumentChunk, DocumentChunkSet
from app.models.document_extraction import DocumentExtraction
from app.models.organization_membership import OrganizationMembership
from app.schemas.document_search import DocumentSearchQuery


class DocumentSearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def statement(*, organization_id: UUID, user_id: UUID, data: DocumentSearchQuery):
        latest = aliased(DocumentChunkSet)
        latest_id = (
            select(latest.id)
            .where(latest.document_id == CandidateDocument.id)
            .order_by(latest.created_at.desc(), latest.id.desc())
            .limit(1)
            .correlate(CandidateDocument)
            .scalar_subquery()
        )
        vector = search_vector(DocumentChunk.text)
        query = search_query(data.q)
        member = exists(
            select(OrganizationMembership.id).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
            )
        )
        matches = (
            select(
                DocumentChunk.chunk_set_id,
                DocumentChunk.position.label("chunk_position"),
                CandidateDocument.id.label("document_id"),
                func.ts_rank_cd(vector, query, 32).label("score"),
            )
            .select_from(DocumentChunk)
            .join(DocumentChunkSet)
            .join(DocumentExtraction)
            .join(CandidateDocument)
            .where(
                member,
                CandidateDocument.organization_id == organization_id,
                CandidateDocument.status == "ready",
                DocumentExtraction.status == "succeeded",
                DocumentChunkSet.id == latest_id,
                vector.bool_op("@@")(query),
            )
        )
        if data.candidate_id is not None:
            matches = matches.where(CandidateDocument.candidate_id == data.candidate_id)
        if data.document_id is not None:
            matches = matches.where(CandidateDocument.id == data.document_id)
        matches = matches.cte("search_matches")
        total = (
            select(func.count().label("total")).select_from(matches).cte("search_total")
        )
        page = (
            select(matches)
            .order_by(
                matches.c.score.desc(),
                matches.c.document_id,
                matches.c.chunk_set_id,
                matches.c.chunk_position,
            )
            .limit(data.limit)
            .offset(data.offset)
            .cte("search_page")
        )
        rows = (
            total.outerjoin(page, true())
            .outerjoin(
                DocumentChunk,
                and_(
                    DocumentChunk.chunk_set_id == page.c.chunk_set_id,
                    DocumentChunk.position == page.c.chunk_position,
                ),
            )
            .outerjoin(DocumentChunkSet, DocumentChunkSet.id == page.c.chunk_set_id)
            .outerjoin(CandidateDocument, CandidateDocument.id == page.c.document_id)
            .outerjoin(Candidate, Candidate.id == CandidateDocument.candidate_id)
        )
        return (
            select(
                total.c.total,
                page.c.score,
                page.c.chunk_set_id,
                page.c.chunk_position,
                CandidateDocument.id.label("document_id"),
                CandidateDocument.candidate_id,
                Candidate.full_name.label("candidate_name"),
                CandidateDocument.filename,
                DocumentChunk.start_offset,
                DocumentChunk.end_offset,
                DocumentChunk.text,
                DocumentChunk.sha256.label("chunk_sha256"),
                DocumentChunkSet.source_document_sha256,
                DocumentChunkSet.source_text_sha256,
            )
            .select_from(rows)
            .order_by(
                page.c.score.desc(),
                page.c.document_id,
                page.c.chunk_set_id,
                page.c.chunk_position,
            )
        )

    async def search(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        data: DocumentSearchQuery,
        timeout_ms: int,
    ) -> tuple[list[dict], int]:
        await self._session.execute(
            select(func.set_config("statement_timeout", f"{timeout_ms}ms", True))
        )
        rows = (
            (
                await self._session.execute(
                    self.statement(
                        organization_id=organization_id,
                        user_id=user_id,
                        data=data,
                    )
                )
            )
            .mappings()
            .all()
        )
        total = rows[0]["total"]
        return [
            {key: value for key, value in row.items() if key != "total"}
            for row in rows
            if row["chunk_set_id"] is not None
        ], total
