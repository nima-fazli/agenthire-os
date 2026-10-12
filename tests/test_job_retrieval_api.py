from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes.job_retrieval import get_job_retrieval_service
from app.core.errors import AppError, NotFoundError
from app.main import app
from app.models.user import User
from app.schemas.job_retrieval import JobCandidatePage, JobSearchProfileRead
from app.services.job_retrieval import JobRetrievalService


@pytest.fixture
def context():
    user = User(
        id=uuid4(), email="retrieval@example.com", password_hash="hash", is_active=True
    )
    org, job, now = uuid4(), uuid4(), datetime.now(UTC)
    service = AsyncMock(spec=JobRetrievalService)
    profile = JobSearchProfileRead(
        job_id=job, q="Python", revision=1, created_at=now, updated_at=now
    )
    service.put_profile.return_value = service.get_profile.return_value = profile
    service.retrieve.return_value = JobCandidatePage(
        job_id=job,
        q="Python",
        profile_revision=1,
        profile_updated_at=now,
        applicants_only=False,
        items=[],
        total=0,
        limit=10,
        offset=0,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_job_retrieval_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(
                client=client,
                service=service,
                user=user,
                org=org,
                job=job,
                path=f"/organizations/{org}/jobs/{job}",
            )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "method, suffix, name",
    [
        ("PUT", "/search-profile", "put_profile"),
        ("GET", "/search-profile", "get_profile"),
        ("GET", "/candidate-retrieval", "retrieve"),
    ],
)
def test_routes_are_private_and_forward_authenticated_scope(
    context, method, suffix, name
):
    kwargs = {"json": {"q": "Python"}} if method == "PUT" else {}
    response = context.client.request(method, context.path + suffix, **kwargs)
    assert (
        response.status_code == 200
        and response.headers["cache-control"] == "private, no-store"
    )
    assert getattr(context.service, name).await_args.kwargs == {
        "job_id": context.job,
        "organization_id": context.org,
        "user_id": context.user.id,
    }
    assert (
        "storage_key" not in response.text and "updated_by_user_id" not in response.text
    )


def test_retrieval_parameters_are_validated_and_forwarded(context):
    response = context.client.get(
        context.path + "/candidate-retrieval",
        params={"applicants_only": "true", "limit": 2, "offset": 3},
    )
    assert response.status_code == 200
    data = context.service.retrieve.await_args.args[0]
    assert data.applicants_only and data.limit == 2 and data.offset == 3


@pytest.mark.parametrize(
    "payload",
    [{}, {"q": " "}, {"q": "& |"}, {"q": "py\x00thon"}, {"q": "Python", "revision": 9}],
    ids=["missing", "blank", "operators", "nul", "revision"],
)
def test_invalid_profile_body_never_reaches_service(context, payload):
    assert (
        context.client.put(context.path + "/search-profile", json=payload).status_code
        == 422
    )
    context.service.put_profile.assert_not_awaited()


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 51},
        {"offset": -1},
        {"offset": 1001},
        {"q": "override"},
        {"user_id": str(uuid4())},
        {"applicants_only": "bad"},
    ],
    ids=["zero", "limit", "negative", "offset", "query", "user", "bool"],
)
def test_invalid_retrieval_query_never_reaches_service(context, params):
    assert (
        context.client.get(
            context.path + "/candidate-retrieval", params=params
        ).status_code
        == 422
    )
    context.service.retrieve.assert_not_awaited()


@pytest.mark.parametrize(
    "method, suffix",
    [
        ("PUT", "/search-profile"),
        ("GET", "/search-profile"),
        ("GET", "/candidate-retrieval"),
    ],
)
def test_all_routes_require_bearer_token(context, method, suffix):
    app.dependency_overrides.pop(get_current_user)
    kwargs = {"json": {"q": "Python"}} if method == "PUT" else {}
    assert (
        context.client.request(method, context.path + suffix, **kwargs).status_code
        == 401
    )
    assert context.service.mock_calls == []


@pytest.mark.parametrize(
    "code", ["ORGANIZATION_NOT_FOUND", "JOB_NOT_FOUND", "JOB_SEARCH_PROFILE_NOT_FOUND"]
)
def test_hidden_scope_and_missing_profile_return_domain_errors(context, code):
    context.service.retrieve.side_effect = NotFoundError(code=code, message="Hidden")
    response = context.client.get(context.path + "/candidate-retrieval")
    assert response.status_code == 404 and response.json()["error"]["code"] == code


def test_retrieval_timeout_returns_safe_503(context):
    context.service.retrieve.side_effect = AppError(
        code="CANDIDATE_RETRIEVAL_TIMEOUT", message="Timed out", status_code=503
    )
    response = context.client.get(context.path + "/candidate-retrieval")
    assert (
        response.status_code == 503
        and response.json()["error"]["code"] == "CANDIDATE_RETRIEVAL_TIMEOUT"
    )
