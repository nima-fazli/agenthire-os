from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes.semantic_retrieval import get_semantic_retrieval_service
from app.core.errors import AppError, ConflictError, NotFoundError
from app.main import app
from app.schemas.semantic_retrieval import SemanticPage
from app.services.semantic_retrieval import SemanticRetrievalService


@pytest.fixture
def context():
    org, user, job = uuid4(), uuid4(), uuid4()
    service = AsyncMock(spec=SemanticRetrievalService)
    service.search.return_value = SemanticPage(model_digest="a" * 64, mode="hybrid",
        score_kind="reciprocal_rank_fusion", unit="chunk", eligible_chunks=1, embedded_chunks=0,
        pool_truncated=False, pooled_count=0, limit=10, items=[])
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user)
    app.dependency_overrides[get_semantic_retrieval_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(client=client, service=service, org=org, user=user, job=job,
                document=f"/organizations/{org}/semantic-search",
                candidate=f"/organizations/{org}/jobs/{job}/semantic-candidate-retrieval")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize("job", [True, False])
def test_post_is_private_and_passes_authenticated_scope(context, job):
    c = context
    response = c.client.post(c.candidate if job else c.document, json={} if job else {"q": "رزومه"})
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    assert response.json()["model_digest"] == "a" * 64
    assert "vector" not in response.json()
    assert c.service.search.await_args.kwargs == {"organization_id": c.org, "user_id": c.user} | (
        {"job_id": c.job} if job else {})


@pytest.mark.parametrize("job", [True, False])
def test_routes_require_authentication(context, job):
    app.dependency_overrides.pop(get_current_user)
    response = context.client.post(context.candidate if job else context.document,
                                   json={} if job else {"q": "Python"})
    assert response.status_code == 401
    context.service.search.assert_not_awaited()


@pytest.mark.parametrize("payload", [{"mode": "cloud"}, {"limit": "1"}, {"model_digest": "a" * 64}])
def test_invalid_requests_do_not_reach_service(context, payload):
    assert context.client.post(context.document, json={"q": "Python"} | payload).status_code == 422
    context.service.search.assert_not_awaited()


@pytest.mark.parametrize("error,status", [
    (NotFoundError(code="ORGANIZATION_NOT_FOUND", message="Hidden."), 404),
    (ConflictError(code="JOB_SEARCH_PROFILE_CHANGED", message="Retry."), 409),
    (AppError(code="SEMANTIC_DISABLED", message="Disabled.", status_code=503), 503),
])
def test_domain_errors_keep_safe_error_contract(context, error, status):
    context.service.search.side_effect = error
    response = context.client.post(context.candidate, json={})
    assert response.status_code == status and response.json()["error"]["code"] == error.code
