from uuid import UUID

from sqlalchemy import and_, delete, func, insert, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.text_search import search_query, search_vector
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.document_chunk import DocumentChunk, DocumentChunkSet
from app.models.document_extraction import DocumentExtraction
from app.models.job import Job
from app.models.job_matching import JobMatchCriterion, JobMatchProfile
from app.repositories.job_retrieval import JobRetrievalRepository
from app.schemas.document_search import DocumentSearchHit

PROFILE_KEYS = ("job_id", "revision", "created_at", "updated_at")
CRITERION_KEYS = ("position", "key", "label", "q", "importance")


class JobMatchingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def profile_scope(*, organization_id: UUID, user_id: UUID, job_id: UUID):
        return (
            select(*(getattr(JobMatchProfile, key) for key in PROFILE_KEYS))
            .select_from(JobMatchProfile)
            .join(Job)
            .where(
                Job.id == job_id,
                Job.organization_id == organization_id,
                JobRetrievalRepository.membership(organization_id, user_id),
            )
        )

    async def lock_job(self, **scope):
        return await JobRetrievalRepository(self._session).lock_job(**scope)

    async def get_profile(self, **scope) -> dict | None:
        profile = self.profile_scope(**scope).subquery()
        statement = (
            select(
                profile,
                JobMatchCriterion.position,
                JobMatchCriterion.key,
                JobMatchCriterion.label,
                JobMatchCriterion.query_text.label("q"),
                JobMatchCriterion.importance,
            )
            .select_from(
                profile.join(
                    JobMatchCriterion, JobMatchCriterion.job_id == profile.c.job_id
                )
            )
            .order_by(JobMatchCriterion.position)
        )
        rows = (await self._session.execute(statement)).mappings().all()
        if not rows:
            return None
        return {key: rows[0][key] for key in PROFILE_KEYS} | {
            "criteria": [{key: row[key] for key in CRITERION_KEYS} for row in rows]
        }

    async def save_profile(
        self,
        current: dict | None,
        *,
        criteria: list[dict],
        organization_id: UUID,
        user_id: UUID,
        job_id: UUID,
    ) -> dict | None:
        if (
            current is not None
            and [
                {key: value for key, value in item.items() if key != "position"}
                for item in current["criteria"]
            ]
            == criteria
        ):
            return current
        if current is None:
            self._session.add(
                JobMatchProfile(job_id=job_id, revision=1, updated_by_user_id=user_id)
            )
            await self._session.flush()
        else:
            await self._session.execute(
                update(JobMatchProfile)
                .where(JobMatchProfile.job_id == job_id)
                .values(
                    revision=current["revision"] + 1,
                    updated_by_user_id=user_id,
                )
            )
            await self._session.execute(
                delete(JobMatchCriterion).where(JobMatchCriterion.job_id == job_id)
            )
        await self._session.execute(
            insert(JobMatchCriterion),
            [
                {
                    "job_id": job_id,
                    "position": position,
                    "key": item["key"],
                    "label": item["label"],
                    "query_text": item["q"],
                    "importance": item["importance"],
                }
                for position, item in enumerate(criteria)
            ],
        )
        return await self.get_profile(
            organization_id=organization_id, user_id=user_id, job_id=job_id
        )

    @staticmethod
    def evidence_statement(
        *, organization_id: UUID, user_id: UUID, job_id: UUID, candidate_id: UUID
    ):
        profile = (
            JobMatchingRepository.profile_scope(
                organization_id=organization_id, user_id=user_id, job_id=job_id
            )
            .add_columns(
                Candidate.id.label("candidate_id"),
                Candidate.full_name.label("candidate_name"),
            )
            .join(Candidate, true())
            .where(
                Candidate.id == candidate_id,
                Candidate.organization_id == organization_id,
            )
            .cte("evidence_profile")
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
        sources = (
            select(
                CandidateDocument.id.label("document_id"),
                CandidateDocument.filename,
                DocumentExtraction.status.label("extraction_status"),
                latest_id.label("chunk_set_id"),
            )
            .select_from(CandidateDocument)
            .outerjoin(DocumentExtraction)
            .where(
                CandidateDocument.organization_id == organization_id,
                CandidateDocument.candidate_id == candidate_id,
                CandidateDocument.status == "ready",
            )
            .cte("evidence_sources")
        )
        stats = (
            select(
                func.count().label("ready_documents"),
                func.count()
                .filter(
                    and_(
                        sources.c.extraction_status == "succeeded",
                        sources.c.chunk_set_id.is_not(None),
                    )
                )
                .label("indexed_documents"),
            )
            .select_from(sources)
            .cte("evidence_source_counts")
        )
        vector = search_vector(DocumentChunk.text)
        query = search_query(JobMatchCriterion.query_text)
        score = func.ts_rank_cd(vector, query, 32)
        matches = (
            select(
                JobMatchCriterion.position.label("criterion_position"),
                sources.c.document_id,
                DocumentChunk.chunk_set_id,
                DocumentChunk.position.label("chunk_position"),
                score.label("score"),
                func.row_number()
                .over(
                    partition_by=JobMatchCriterion.position,
                    order_by=(
                        score.desc(),
                        sources.c.document_id,
                        DocumentChunk.chunk_set_id,
                        DocumentChunk.position,
                    ),
                )
                .label("witness_order"),
            )
            .select_from(
                profile.join(
                    JobMatchCriterion, JobMatchCriterion.job_id == profile.c.job_id
                )
                .join(sources, true())
                .join(DocumentChunkSet, DocumentChunkSet.id == sources.c.chunk_set_id)
                .join(DocumentChunk)
            )
            .where(
                sources.c.extraction_status == "succeeded",
                vector.bool_op("@@")(query),
            )
            .cte("criterion_matches")
        )
        best = select(matches).where(matches.c.witness_order == 1).cte("criterion_best")
        rows = (
            profile.join(
                JobMatchCriterion, JobMatchCriterion.job_id == profile.c.job_id
            )
            .join(stats, true())
            .outerjoin(best, best.c.criterion_position == JobMatchCriterion.position)
            .outerjoin(CandidateDocument, CandidateDocument.id == best.c.document_id)
            .outerjoin(DocumentChunkSet, DocumentChunkSet.id == best.c.chunk_set_id)
            .outerjoin(
                DocumentChunk,
                and_(
                    DocumentChunk.chunk_set_id == best.c.chunk_set_id,
                    DocumentChunk.position == best.c.chunk_position,
                ),
            )
        )
        return (
            select(
                profile.c.job_id,
                profile.c.candidate_id,
                profile.c.candidate_name,
                profile.c.revision.label("profile_revision"),
                profile.c.updated_at.label("profile_updated_at"),
                func.statement_timestamp().label("observed_at"),
                stats.c.ready_documents,
                stats.c.indexed_documents,
                JobMatchCriterion.position,
                JobMatchCriterion.key,
                JobMatchCriterion.label,
                JobMatchCriterion.query_text.label("q"),
                JobMatchCriterion.importance,
                best.c.document_id,
                best.c.chunk_set_id,
                best.c.chunk_position,
                best.c.score,
                CandidateDocument.filename,
                DocumentChunk.start_offset,
                DocumentChunk.end_offset,
                DocumentChunk.text,
                DocumentChunk.sha256.label("chunk_sha256"),
                DocumentChunkSet.source_document_sha256,
                DocumentChunkSet.source_text_sha256,
            )
            .select_from(rows)
            .order_by(JobMatchCriterion.position)
        )

    async def evidence(self, *, timeout_ms: int, **scope) -> dict | None:
        await self._session.execute(
            select(func.set_config("statement_timeout", f"{timeout_ms}ms", True))
        )
        rows = (
            (await self._session.execute(self.evidence_statement(**scope)))
            .mappings()
            .all()
        )
        if not rows:
            return None
        meta = (
            "job_id",
            "candidate_id",
            "candidate_name",
            "profile_revision",
            "profile_updated_at",
            "observed_at",
            "ready_documents",
            "indexed_documents",
        )
        return {key: rows[0][key] for key in meta} | {
            "criteria": [
                {key: row[key] for key in CRITERION_KEYS}
                | {
                    "evidence": {
                        key: row[key] for key in DocumentSearchHit.model_fields
                    }
                    if row["chunk_set_id"] is not None
                    else None
                }
                for row in rows
            ]
        }
