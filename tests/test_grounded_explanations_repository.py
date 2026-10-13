import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.grounded_explanations import ground, prepare
from app.repositories.grounded_explanations import GroundedExplanationRepository
from scripts.grounded_explanations_evaluation import example_snapshot


def test_final_statement_rechecks_scope_profile_exact_source_and_quote_terms():
    snapshot, org, user = example_snapshot(), uuid4(), uuid4()
    assignments, _, _ = prepare(snapshot)
    citations = ground({"quotes": [{"criterion": "skill", "source": "s0", "quote": "Python"}]}, assignments)
    compiled = GroundedExplanationRepository.statement(snapshot, citations,
        organization_id=org, user_id=user).compile(dialect=postgresql.dialect())
    sql = str(compiled)
    for part in ("organization_memberships", "jobs.organization_id", "candidates.organization_id",
                 "job_match_profiles.revision", "job_match_criteria.query_text", "sha256(convert_to",
                 "substr(", "document_chunk_sets_1.created_at DESC", "@@", "validated_at"):
        assert part in sql
    assert org in compiled.params.values() and user in compiled.params.values()
    assert "Python" not in sql and "Python" in compiled.params.values()


def test_repository_uses_transaction_local_timeout_without_commit():
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.mappings.return_value.one.return_value = {"authorized": True}
    session.execute.return_value = result
    value = asyncio.run(GroundedExplanationRepository(session).check(example_snapshot(), {},
        organization_id=uuid4(), user_id=uuid4(), timeout_ms=1500))
    assert value["authorized"] and session.execute.await_count == 2
    assert "set_config" in str(session.execute.await_args_list[0].args[0])
    session.commit.assert_not_awaited()
