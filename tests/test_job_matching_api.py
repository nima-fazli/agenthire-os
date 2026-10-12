from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes.job_matching import get_job_matching_service
from app.core.errors import AppError, NotFoundError
from app.main import app
from app.models.user import User
from app.schemas.job_matching import JobMatchEvidenceRead, JobMatchProfileRead
from app.services.job_matching import JobMatchingService


@pytest.fixture
def context():
    user = User(
        id=uuid4(), email="matching@example.com", password_hash="hash", is_active=True
    )
    org, job, candidate, now = uuid4(), uuid4(), uuid4(), datetime.now(UTC)
    item = {
        "key": "python",
        "label": "Python",
        "q": "Python",
        "importance": "required",
        "position": 0,
    }
    service = AsyncMock(spec=JobMatchingService)
    service.put_profile.return_value = service.get_profile.return_value = (
        JobMatchProfileRead(
            job_id=job, revision=1, created_at=now, updated_at=now, criteria=[item]
        )
    )
    service.evidence.return_value = JobMatchEvidenceRead(
        job_id=job,
        candidate_id=candidate,
        candidate_name="Ada",
        profile_revision=1,
        profile_updated_at=now,
        observed_at=now,
        criteria=[item | {"evidence": None}],
        summary={
            "required_total": 1,
            "required_with_evidence": 0,
            "preferred_total": 0,
            "preferred_with_evidence": 0,
            "ready_documents": 0,
            "indexed_documents": 0,
            "source_status": "no_documents",
        },
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_job_matching_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(
                client=client,
                service=service,
                user=user,
                org=org,
                job=job,
                candidate=candidate,
                profile=f"/organizations/{org}/jobs/{job}/match-profile",
                evidence=f"/organizations/{org}/jobs/{job}/candidates/{candidate}/match-evidence",
                payload={
                    "criteria": [
                        {key: value for key, value in item.items() if key != "position"}
                    ]
                },
            )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("operation", ["put", "get", "evidence"])
def test_successful_routes_are_private_and_use_authenticated_scope(context, operation):
    if operation == "put":
        response = context.client.put(context.profile, json=context.payload)
    else:
        response = context.client.get(
            context.evidence if operation == "evidence" else context.profile
        )
    assert (
        response.status_code == 200
        and response.headers["cache-control"] == "private, no-store"
    )
    kwargs = {
        "organization_id": context.org,
        "job_id": context.job,
        "user_id": context.user.id,
    }
    if operation == "evidence":
        kwargs["candidate_id"] = context.candidate
    assert (
        getattr(
            context.service,
            "put_profile"
            if operation == "put"
            else "get_profile"
            if operation == "get"
            else "evidence",
        ).await_args.kwargs
        == kwargs
    )
    assert (
        "updated_by_user_id" not in response.text and "storage_key" not in response.text
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"criteria": []},
        {"criteria": [{"key": "python", "label": "Python", "q": " "}]},
        {
            "criteria": [{"key": "python", "label": "Python", "q": "Python"}],
            "revision": 2,
        },
    ],
    ids=["missing", "empty", "blank-q", "revision"],
)
def test_invalid_profile_never_reaches_service(context, payload):
    assert context.client.put(context.profile, json=payload).status_code == 422
    context.service.put_profile.assert_not_awaited()


@pytest.mark.parametrize(
    "params", [{"q": "override"}, {"user_id": str(uuid4())}, {"score": 1}]
)
def test_evidence_rejects_client_overrides(context, params):
    assert context.client.get(context.evidence, params=params).status_code == 422
    context.service.evidence.assert_not_awaited()


@pytest.mark.parametrize("operation", ["put", "get", "evidence"])
def test_every_route_requires_bearer_authentication(context, operation):
    app.dependency_overrides.pop(get_current_user)
    if operation == "put":
        response = context.client.put(context.profile, json=context.payload)
    else:
        response = context.client.get(
            context.evidence if operation == "evidence" else context.profile
        )
    assert response.status_code == 401 and context.service.mock_calls == []


@pytest.mark.parametrize(
    "code",
    [
        "ORGANIZATION_NOT_FOUND",
        "JOB_NOT_FOUND",
        "CANDIDATE_NOT_FOUND",
        "JOB_MATCH_PROFILE_NOT_FOUND",
    ],
)
def test_hidden_resources_return_expected_domain_errors(context, code):
    context.service.evidence.side_effect = NotFoundError(code=code, message="Hidden")
    response = context.client.get(context.evidence)
    assert response.status_code == 404 and response.json()["error"]["code"] == code


def test_database_deadline_returns_safe_503(context):
    context.service.evidence.side_effect = AppError(
        code="MATCH_EVIDENCE_TIMEOUT", message="Timed out", status_code=503
    )
    response = context.client.get(context.evidence)
    assert (
        response.status_code == 503
        and response.json()["error"]["code"] == "MATCH_EVIDENCE_TIMEOUT"
    )
