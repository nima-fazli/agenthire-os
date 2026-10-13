import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.semantic_embeddings import EmbeddingFailure, ModelIdentity
from app.schemas.semantic_retrieval import SemanticDocumentQuery, SemanticJobQuery
from app.services.semantic_retrieval import SemanticRetrievalService


@pytest.fixture
def context():
    session = AsyncMock(spec=AsyncSession)
    encoder = AsyncMock()
    encoder.identity.return_value = ModelIdentity("a" * 64)
    encoder.encode.return_value = ((1.,) + (0.,) * 1023,)
    service = SemanticRetrievalService(session, Settings(_env_file=None, semantic_enabled=True), encoder)
    service._memberships = AsyncMock()
    service._profiles = AsyncMock()
    service._profiles.get_profile.return_value = SimpleNamespace(query_text="Python", revision=2,
                                                                 updated_at=datetime.now(UTC))
    service._jobs = AsyncMock()
    service._repository = AsyncMock()
    service._repository.search.return_value = {"authorized": True, "job_exists": True,
        "profile_current": True, "eligible_chunks": 3, "embedded_chunks": 1, "pool_truncated": False, "rows": []}
    return SimpleNamespace(service=service, encoder=encoder, session=session,
                           scope={"organization_id": uuid4(), "user_id": uuid4()})


@pytest.mark.parametrize("job", [True, False])
def test_query_is_pinned_and_read_transactions_close_before_and_after_model(context, job):
    c = context
    kwargs = c.scope | ({"job_id": uuid4()} if job else {})
    data = SemanticJobQuery() if job else SemanticDocumentQuery(q="Python")
    page = asyncio.run(c.service.search(data, **kwargs))
    assert page.model_digest == "a" * 64 and page.embedded_chunks == 1 and page.eligible_chunks == 3
    assert page.profile_revision == (2 if job else None)
    assert c.session.rollback.await_count == 2
    c.session.commit.assert_not_awaited()
    assert c.encoder.encode.await_args.args[0][0].endswith("\nQuery: Python")
    assert c.service._repository.search.await_args.kwargs["identity"] == ModelIdentity("a" * 64)


@pytest.mark.parametrize("issue,code", [
    ("nonmember", "ORGANIZATION_NOT_FOUND"), ("disabled", "SEMANTIC_DISABLED"),
    ("missing_profile", "JOB_SEARCH_PROFILE_NOT_FOUND"),
    ("revoked", "ORGANIZATION_NOT_FOUND"), ("deleted_job", "JOB_NOT_FOUND"),
    ("changed_profile", "JOB_SEARCH_PROFILE_CHANGED"), ("model", "EMBEDDING_MODEL_CHANGED"),
    ("vector", "EMBEDDING_VECTOR_INVALID"), ("deadline", "SEMANTIC_MODEL_TIMEOUT"),
    ("db_timeout", "SEMANTIC_RETRIEVAL_TIMEOUT"),
])
def test_failures_are_safe_and_rollback(context, issue, code):
    c = context
    job = issue in {"missing_profile", "deleted_job", "changed_profile"}
    if issue == "nonmember": c.service._memberships.get_by_user_and_organization.return_value = None
    elif issue == "disabled": c.service._settings.semantic_enabled = False
    elif issue == "missing_profile": c.service._profiles.get_profile.return_value = None
    elif issue in {"revoked", "deleted_job", "changed_profile"}:
        c.service._repository.search.return_value[{"revoked": "authorized", "deleted_job": "job_exists",
                                                   "changed_profile": "profile_current"}[issue]] = False
    elif issue == "model": c.encoder.identity.side_effect = EmbeddingFailure(code)
    elif issue == "vector": c.encoder.encode.return_value = ()
    elif issue == "deadline": c.encoder.identity.side_effect = TimeoutError()
    else:
        error = SimpleNamespace(sqlstate="57014")
        c.service._repository.search.side_effect = DBAPIError("private", {}, error, False)
    with pytest.raises(AppError) as caught:
        asyncio.run(c.service.search(SemanticJobQuery() if job else SemanticDocumentQuery(q="Python"),
                                    **(c.scope | ({"job_id": uuid4()} if job else {}))))
    assert caught.value.code == code and c.session.rollback.await_count >= 1
    if issue in {"nonmember", "disabled", "missing_profile"}:
        c.encoder.identity.assert_not_awaited()


def test_cancellation_propagates_and_cannot_leave_local_timeout_open(context):
    context.encoder.encode.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(context.service.search(SemanticDocumentQuery(q="Python"), **context.scope))
    assert context.session.rollback.await_count == 2


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_nonempty_results_serialize_independent_branch_provenance(context, mode):
    candidate = uuid4()
    evidence = {"candidate_id": candidate, "candidate_name": "Synthetic",
        "document_id": uuid4(), "filename": "synthetic.pdf", "chunk_set_id": uuid4(),
        "chunk_position": 0, "start_offset": 0, "end_offset": 6, "text": "Python",
        "chunk_sha256": "a" * 64, "source_document_sha256": "b" * 64,
        "source_text_sha256": "c" * 64, "score": 1.0, "embedding_job_id": None}
    context.service._repository.search.return_value["rows"] = [evidence | {"branch": "lexical"},
        evidence | {"branch": "semantic", "document_id": uuid4(), "embedding_job_id": uuid4()}]
    page = asyncio.run(context.service.search(SemanticJobQuery(mode=mode), job_id=uuid4(), **context.scope))
    assert len(page.items) == 1 and page.items[0].score == 1.0
    assert len(page.items[0].evidence) == (2 if mode == "hybrid" else 1)
    assert "vector" not in page.model_dump()
    if mode == "hybrid":
        assert page.items[0].evidence[0].embedding_job_id is None
        assert page.items[0].evidence[1].embedding_job_id is not None
