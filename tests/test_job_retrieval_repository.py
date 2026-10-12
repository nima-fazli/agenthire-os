import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.job_retrieval import JobRetrievalRepository
from app.schemas.job_retrieval import JobCandidateQuery


def statement(**kwargs):
    return JobRetrievalRepository.statement(
        organization_id=uuid4(),
        user_id=uuid4(),
        job_id=uuid4(),
        data=JobCandidateQuery(**kwargs),
    )


def sql(value):
    return str(value.compile(dialect=postgresql.dialect()))


def test_profile_and_evidence_are_scoped_in_one_statement():
    value = sql(statement())
    for required in (
        "organization_memberships.user_id =",
        "jobs.organization_id =",
        "candidate_documents.organization_id =",
        "candidates.organization_id =",
        "candidate_documents.status =",
        "document_extractions.status =",
        "plainto_tsquery",
        "retrieval_profile.query",
        "@@",
    ):
        assert required in value
    assert "storage_key" not in value and "updated_by_user_id" not in value


def test_best_chunk_per_candidate_precedes_count_and_pagination():
    value = sql(statement(limit=2, offset=3))
    assert (
        "row_number() OVER (PARTITION BY candidate_documents.candidate_id ORDER BY"
        in value
    )
    assert "WHERE retrieval_matches.evidence_order =" in value
    assert "FROM candidate_best" in value
    assert "candidate_best.score DESC, candidate_best.candidate_id" in value
    assert "LEFT OUTER JOIN candidate_page ON true" in value
    assert "sum(" not in value.lower()
    assert (
        "document_chunk_sets_1.created_at DESC, document_chunk_sets_1.id DESC" in value
    )


def test_applicant_filter_is_an_exists_for_the_same_job_tenant_and_candidate():
    assert "FROM applications" not in sql(statement())
    value = sql(statement(applicants_only=True))
    assert "FROM applications" in value and "applications.organization_id =" in value
    assert "applications.job_id =" in value
    assert "applications.candidate_id = candidate_documents.candidate_id" in value


def test_job_lock_is_scoped_and_locks_the_parent_before_profile_creation():
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.execute.return_value = MagicMock()
    job, org, user = uuid4(), uuid4(), uuid4()
    asyncio.run(
        JobRetrievalRepository(session).lock_job(
            job_id=job, organization_id=org, user_id=user
        )
    )
    value = session.execute.await_args.args[0]
    assert "FOR UPDATE OF jobs" in sql(value)
    assert {job, org, user}.issubset(set(value.compile().params.values()))
    session.commit.assert_not_called()


def test_empty_page_keeps_profile_metadata_and_candidate_count():
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {
            "q": "Python",
            "profile_revision": 2,
            "profile_updated_at": datetime.now(UTC),
            "total": 7,
            "chunk_set_id": None,
        }
    ]
    session.execute.side_effect = [MagicMock(), result]
    page = asyncio.run(
        JobRetrievalRepository(session).retrieve(
            organization_id=uuid4(),
            user_id=uuid4(),
            job_id=uuid4(),
            data=JobCandidateQuery(offset=50),
            timeout_ms=1500,
        )
    )
    assert page["total"] == 7 and page["items"] == [] and page["profile_revision"] == 2
    assert (
        "1500ms" in session.execute.await_args_list[0].args[0].compile().params.values()
    )
    session.commit.assert_not_called()


def test_missing_authorized_profile_is_distinct_from_zero_matches():
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session.execute.side_effect = [MagicMock(), result]
    assert (
        asyncio.run(
            JobRetrievalRepository(session).retrieve(
                organization_id=uuid4(),
                user_id=uuid4(),
                job_id=uuid4(),
                data=JobCandidateQuery(),
                timeout_ms=1500,
            )
        )
        is None
    )


def test_evidence_projection_keeps_profile_metadata_out_of_items():
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    result = MagicMock()
    chunk_set_id = uuid4()
    result.mappings.return_value.all.return_value = [
        {
            "q": "Python",
            "profile_revision": 3,
            "profile_updated_at": datetime.now(UTC),
            "total": 1,
            "chunk_set_id": chunk_set_id,
            "score": 0.5,
        }
    ]
    session.execute.side_effect = [MagicMock(), result]
    page = asyncio.run(
        JobRetrievalRepository(session).retrieve(
            organization_id=uuid4(),
            user_id=uuid4(),
            job_id=uuid4(),
            data=JobCandidateQuery(),
            timeout_ms=1500,
        )
    )
    assert page["items"] == [{"chunk_set_id": chunk_set_id, "score": 0.5}]
    assert page["profile_revision"] == 3 and page["total"] == 1
