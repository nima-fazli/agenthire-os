from uuid import UUID

from sqlalchemy import and_, exists, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.text_search import search_query, search_vector
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.document_chunk import DocumentChunk, DocumentChunkSet
from app.models.document_extraction import DocumentExtraction
from app.models.job import Job
from app.models.job_search_profile import JobSearchProfile
from app.models.organization_membership import OrganizationMembership
from app.schemas.job_retrieval import JobCandidateQuery


class JobRetrievalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def membership(organization_id: UUID, user_id: UUID):
        return exists(
            select(OrganizationMembership.id).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
            )
        )

    async def lock_job(self, *, organization_id: UUID, user_id: UUID, job_id: UUID):
        statement = (
            select(Job.id)
            .where(
                Job.id == job_id,
                Job.organization_id == organization_id,
                self.membership(organization_id, user_id),
            )
            .with_for_update(of=Job)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get_profile(self, *, organization_id: UUID, user_id: UUID, job_id: UUID):
        statement = (
            select(JobSearchProfile)
            .join(Job)
            .where(
                Job.id == job_id,
                Job.organization_id == organization_id,
                self.membership(organization_id, user_id),
            )
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def save_profile(
        self, profile: JobSearchProfile | None, *, job_id: UUID, q: str, user_id: UUID
    ) -> JobSearchProfile:
        if profile is None:
            profile = JobSearchProfile(
                job_id=job_id, query_text=q, revision=1, updated_by_user_id=user_id
            )
            self._session.add(profile)
        elif profile.query_text == q:
            return profile
        else:
            profile.query_text = q
            profile.revision += 1
            profile.updated_by_user_id = user_id
        await self._session.flush()
        await self._session.refresh(profile)
        return profile

    @staticmethod
    def statement(
        *, organization_id: UUID, user_id: UUID, job_id: UUID, data: JobCandidateQuery
    ):
        profile = (
            select(
                JobSearchProfile.query_text.label("q"),
                JobSearchProfile.revision.label("profile_revision"),
                JobSearchProfile.updated_at.label("profile_updated_at"),
                search_query(JobSearchProfile.query_text).label("query"),
            )
            .join(Job)
            .where(
                Job.id == job_id,
                Job.organization_id == organization_id,
                JobRetrievalRepository.membership(organization_id, user_id),
            )
            .cte("retrieval_profile")
        )
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
        score = func.ts_rank_cd(vector, profile.c.query, 32)
        matches = (
            select(
                CandidateDocument.candidate_id,
                CandidateDocument.id.label("document_id"),
                DocumentChunk.chunk_set_id,
                DocumentChunk.position.label("chunk_position"),
                score.label("score"),
                func.row_number()
                .over(
                    partition_by=CandidateDocument.candidate_id,
                    order_by=(
                        score.desc(),
                        CandidateDocument.id,
                        DocumentChunk.chunk_set_id,
                        DocumentChunk.position,
                    ),
                )
                .label("evidence_order"),
            )
            .select_from(profile)
            .join(
                CandidateDocument,
                CandidateDocument.organization_id == organization_id,
            )
            .join(
                Candidate,
                and_(
                    Candidate.id == CandidateDocument.candidate_id,
                    Candidate.organization_id == organization_id,
                ),
            )
            .join(DocumentExtraction)
            .join(DocumentChunkSet)
            .join(DocumentChunk)
            .where(
                CandidateDocument.status == "ready",
                DocumentExtraction.status == "succeeded",
                DocumentChunkSet.id == latest_id,
                vector.bool_op("@@")(profile.c.query),
            )
        )
        if data.applicants_only:
            matches = matches.where(
                exists(
                    select(Application.id).where(
                        Application.organization_id == organization_id,
                        Application.job_id == job_id,
                        Application.candidate_id == CandidateDocument.candidate_id,
                    )
                )
            )
        matches = matches.cte("retrieval_matches")
        best = (
            select(matches).where(matches.c.evidence_order == 1).cte("candidate_best")
        )
        total = (
            select(func.count().label("total")).select_from(best).cte("candidate_total")
        )
        page = (
            select(best)
            .order_by(best.c.score.desc(), best.c.candidate_id)
            .limit(data.limit)
            .offset(data.offset)
            .cte("candidate_page")
        )
        rows = (
            profile.join(total, true())
            .outerjoin(page, true())
            .outerjoin(CandidateDocument, CandidateDocument.id == page.c.document_id)
            .outerjoin(Candidate, Candidate.id == page.c.candidate_id)
            .outerjoin(DocumentChunkSet, DocumentChunkSet.id == page.c.chunk_set_id)
            .outerjoin(
                DocumentChunk,
                and_(
                    DocumentChunk.chunk_set_id == page.c.chunk_set_id,
                    DocumentChunk.position == page.c.chunk_position,
                ),
            )
        )
        return (
            select(
                profile.c.q,
                profile.c.profile_revision,
                profile.c.profile_updated_at,
                total.c.total,
                page.c.score,
                page.c.candidate_id,
                page.c.document_id,
                page.c.chunk_set_id,
                page.c.chunk_position,
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
            .order_by(page.c.score.desc(), page.c.candidate_id)
        )

    async def retrieve(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        job_id: UUID,
        data: JobCandidateQuery,
        timeout_ms: int,
    ) -> dict | None:
        await self._session.execute(
            select(func.set_config("statement_timeout", f"{timeout_ms}ms", True))
        )
        rows = (
            (
                await self._session.execute(
                    self.statement(
                        organization_id=organization_id,
                        user_id=user_id,
                        job_id=job_id,
                        data=data,
                    )
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            return None
        keys = {"q", "profile_revision", "profile_updated_at", "total"}
        return {key: rows[0][key] for key in keys} | {
            "items": [
                {key: value for key, value in row.items() if key not in keys}
                for row in rows
                if row["chunk_set_id"] is not None
            ]
        }
