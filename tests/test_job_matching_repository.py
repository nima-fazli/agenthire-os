import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.job_matching import JobMatchingRepository


def statement():
    return JobMatchingRepository.evidence_statement(
        organization_id=uuid4(), user_id=uuid4(), job_id=uuid4(), candidate_id=uuid4()
    )


def sql():
    return str(statement().compile(dialect=postgresql.dialect()))


def test_profile_candidate_membership_and_sources_share_the_authorized_snapshot():
    value = sql()
    for required in (
        "organization_memberships.user_id =",
        "jobs.organization_id =",
        "candidates.organization_id =",
        "candidate_documents.organization_id =",
        "candidate_documents.candidate_id =",
        "candidate_documents.status =",
        "evidence_sources.extraction_status =",
        "evidence_source_counts",
        "statement_timestamp()",
    ):
        assert required in value
    assert "storage_key" not in value and "updated_by_user_id" not in value


def test_each_criterion_uses_its_own_query_and_stable_best_witness():
    value = sql()
    assert "agenthire_search_text_v1(job_match_criteria.query_text)" in value
    assert (
        "row_number() OVER (PARTITION BY job_match_criteria.position ORDER BY" in value
    )
    assert "WHERE criterion_matches.witness_order =" in value
    assert (
        "LEFT OUTER JOIN criterion_best" in value
        and "ORDER BY job_match_criteria.position" in value
    )
    assert (
        "document_chunk_sets_1.created_at DESC, document_chunk_sets_1.id DESC" in value
    )
    assert "sum(" not in value.lower()


def row(**extra):
    now = datetime.now(UTC)
    return {
        "job_id": uuid4(),
        "candidate_id": uuid4(),
        "candidate_name": "Ada",
        "profile_revision": 1,
        "profile_updated_at": now,
        "observed_at": now,
        "ready_documents": 1,
        "indexed_documents": 0,
        "position": 0,
        "key": "python",
        "label": "Python",
        "q": "Python",
        "importance": "required",
        "chunk_set_id": None,
    } | extra


def execute(rows):
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    session.execute.side_effect = [MagicMock(), result]
    value = asyncio.run(
        JobMatchingRepository(session).evidence(
            organization_id=uuid4(),
            user_id=uuid4(),
            job_id=uuid4(),
            candidate_id=uuid4(),
            timeout_ms=1500,
        )
    )
    session.commit.assert_not_called()
    assert (
        "1500ms" in session.execute.await_args_list[0].args[0].compile().params.values()
    )
    return value


def test_missing_evidence_keeps_every_criterion_and_source_readiness():
    report = execute([row()])
    assert (
        report["criteria"][0]["evidence"] is None
        and report["criteria"][0]["key"] == "python"
    )
    assert report["ready_documents"] == 1 and report["indexed_documents"] == 0


def test_missing_authorized_profile_or_candidate_does_not_return_a_report():
    assert execute([]) is None


def test_witness_projection_preserves_provenance_and_excludes_profile_metadata():
    report = execute(
        [
            row(
                document_id=uuid4(),
                chunk_set_id=uuid4(),
                chunk_position=0,
                score=0.5,
                filename="resume.pdf",
                start_offset=0,
                end_offset=6,
                text="Python",
                chunk_sha256="a" * 64,
                source_document_sha256="b" * 64,
                source_text_sha256="c" * 64,
                indexed_documents=1,
            )
        ]
    )
    witness = report["criteria"][0]["evidence"]
    assert witness["text"] == "Python" and witness["source_text_sha256"] == "c" * 64
    assert (
        "profile_revision" not in witness
        and "q" not in witness
        and "importance" not in witness
    )
