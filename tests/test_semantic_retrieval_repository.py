import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.semantic_embeddings import ModelIdentity
from app.repositories.semantic_retrieval import SemanticRetrievalRepository
from app.schemas.semantic_retrieval import SemanticDocumentQuery, SemanticJobQuery


@pytest.mark.parametrize("job", [True, False])
def test_one_statement_binds_scope_model_source_and_both_branch_windows(job):
    org, user, identifier = uuid4(), uuid4(), uuid4()
    kwargs = {"organization_id": org, "user_id": user, "q": "Python", "vector": (1.,) + (0.,) * 1023,
                  "identity": ModelIdentity("a" * 64)}
    if job:
        kwargs.update(data=SemanticJobQuery(applicants_only=True), job_id=identifier,
                      profile={"revision": 7, "updated_at": datetime.now(UTC)})
    else:
        kwargs.update(data=SemanticDocumentQuery(q="Python", candidate_id=identifier))
    compiled = SemanticRetrievalRepository.statement(**kwargs).compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert sql.count("LEFT OUTER JOIN retrieval_windows") == 1 and "<=>" in sql
    assert "organization_memberships" in sql and "candidate_documents.organization_id" in sql
    assert "sha256(convert_to" in sql and "substr(" in sql and "source_text_sha256" in sql
    assert "document_embedding_jobs.status" in sql and "encoding_version" in sql
    assert "::UUID AS embedding_job_id" in sql and "anon_1.count = document_chunk_sets.chunk_count" in sql
    assert "row_number() OVER" in sql and "ORDER BY document_chunk_sets_1.created_at DESC" in sql
    assert sum(value == 100 for value in compiled.params.values() if isinstance(value, int)) == 4
    assert org in compiled.params.values() and user in compiled.params.values()
    if job:
        assert "applications.organization_id" in sql and "job_search_profiles.revision" in sql
        assert 7 in compiled.params.values()
    assert "Python" not in sql and "a" * 64 not in sql


def test_repository_returns_empty_pool_with_coverage_and_sets_local_deadline():
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.mappings.return_value.all.return_value = [{"authorized": True, "job_exists": True,
        "profile_current": True, "eligible_chunks": 3, "embedded_chunks": 0,
        "pool_truncated": False, "branch": None}]
    session.execute.return_value = result
    repo = SemanticRetrievalRepository(session)
    value = asyncio.run(repo.search(organization_id=uuid4(), user_id=uuid4(),
        data=SemanticDocumentQuery(q="Python"), q="Python", vector=(1.,) + (0.,) * 1023,
        identity=ModelIdentity("a" * 64), timeout_ms=1500))
    assert value["rows"] == [] and value["embedded_chunks"] == 0
    assert "set_config" in str(session.execute.await_args_list[0].args[0])
    session.commit.assert_not_awaited()
