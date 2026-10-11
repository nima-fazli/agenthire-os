from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes.applications import get_application_service
from app.core.errors import ConflictError, NotFoundError
from app.main import app
from app.models.application import Application
from app.models.user import User
from app.schemas.application import ApplicationStatus
from app.services.application import ApplicationService

client = TestClient(app)


def make_user() -> User:
    return User(
        id=uuid4(),
        email="recruiter@example.com",
        password_hash="hashed-secret",
        is_active=True,
    )


def override_authenticated_user(user: User) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_create_application_api() -> None:
    user = make_user()
    organization_id = uuid4()
    job_id = uuid4()
    candidate_id = uuid4()
    application_id = uuid4()
    now = datetime.now(UTC)

    service = AsyncMock(spec=ApplicationService)
    service.create.return_value = Application(
        id=application_id,
        organization_id=organization_id,
        job_id=job_id,
        candidate_id=candidate_id,
        status="applied",
        created_at=now,
        updated_at=now,
    )

    override_authenticated_user(user)
    app.dependency_overrides[get_application_service] = lambda: service

    try:
        response = client.post(
            f"/organizations/{organization_id}/applications",
            json={"job_id": str(job_id), "candidate_id": str(candidate_id)},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201

    body = response.json()
    assert body["id"] == str(application_id)
    assert body["job_id"] == str(job_id)
    assert body["candidate_id"] == str(candidate_id)
    assert body["status"] == "applied"

    invocation = service.create.await_args
    data = invocation.args[0]

    assert data.job_id == job_id
    assert data.candidate_id == candidate_id
    assert invocation.kwargs == {
        "organization_id": organization_id,
        "user_id": user.id,
    }


def test_create_application_api_returns_duplicate_conflict() -> None:
    user = make_user()
    organization_id = uuid4()
    job_id = uuid4()
    candidate_id = uuid4()

    service = AsyncMock(spec=ApplicationService)
    service.create.side_effect = ConflictError(
        code="APPLICATION_ALREADY_EXISTS",
        message="Application already exists for this job and candidate.",
        details={
            "organization_id": str(organization_id),
            "job_id": str(job_id),
            "candidate_id": str(candidate_id),
        },
    )

    override_authenticated_user(user)
    app.dependency_overrides[get_application_service] = lambda: service

    try:
        response = client.post(
            f"/organizations/{organization_id}/applications",
            json={"job_id": str(job_id), "candidate_id": str(candidate_id)},
        )
    finally:
        clear_overrides()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPLICATION_ALREADY_EXISTS"


def test_list_applications_api() -> None:
    user = make_user()
    organization_id = uuid4()
    now = datetime.now(UTC)

    service = AsyncMock(spec=ApplicationService)
    service.list_for_user.return_value = [
        Application(
            id=uuid4(),
            organization_id=organization_id,
            job_id=uuid4(),
            candidate_id=uuid4(),
            status="applied",
            created_at=now,
            updated_at=now,
        ),
        Application(
            id=uuid4(),
            organization_id=organization_id,
            job_id=uuid4(),
            candidate_id=uuid4(),
            status="screening",
            created_at=now,
            updated_at=now,
        ),
    ]

    override_authenticated_user(user)
    app.dependency_overrides[get_application_service] = lambda: service

    try:
        response = client.get(f"/organizations/{organization_id}/applications")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert [item["status"] for item in response.json()] == ["applied", "screening"]


def test_get_application_api() -> None:
    user = make_user()
    organization_id = uuid4()
    application_id = uuid4()
    now = datetime.now(UTC)

    service = AsyncMock(spec=ApplicationService)
    service.get_for_user.return_value = Application(
        id=application_id,
        organization_id=organization_id,
        job_id=uuid4(),
        candidate_id=uuid4(),
        status="offer",
        created_at=now,
        updated_at=now,
    )

    override_authenticated_user(user)
    app.dependency_overrides[get_application_service] = lambda: service

    try:
        response = client.get(
            f"/organizations/{organization_id}/applications/{application_id}"
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json()["id"] == str(application_id)
    assert response.json()["status"] == "offer"


def test_get_application_api_returns_not_found() -> None:
    user = make_user()
    organization_id = uuid4()
    application_id = uuid4()

    service = AsyncMock(spec=ApplicationService)
    service.get_for_user.side_effect = NotFoundError(
        code="APPLICATION_NOT_FOUND",
        message="Application was not found.",
        details={
            "organization_id": str(organization_id),
            "application_id": str(application_id),
        },
    )

    override_authenticated_user(user)
    app.dependency_overrides[get_application_service] = lambda: service

    try:
        response = client.get(
            f"/organizations/{organization_id}/applications/{application_id}"
        )
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "APPLICATION_NOT_FOUND"


def test_application_api_hides_organization_from_non_member() -> None:
    user = make_user()
    organization_id = uuid4()

    service = AsyncMock(spec=ApplicationService)
    service.list_for_user.side_effect = NotFoundError(
        code="ORGANIZATION_NOT_FOUND",
        message="Organization was not found.",
        details={"organization_id": str(organization_id)},
    )

    override_authenticated_user(user)
    app.dependency_overrides[get_application_service] = lambda: service

    try:
        response = client.get(f"/organizations/{organization_id}/applications")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ORGANIZATION_NOT_FOUND"


def test_application_api_requires_authentication() -> None:
    organization_id = uuid4()

    response = client.get(f"/organizations/{organization_id}/applications")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"


@pytest.fixture
def authenticated_application_service():
    user = make_user()
    service = AsyncMock(spec=ApplicationService)

    override_authenticated_user(user)
    app.dependency_overrides[get_application_service] = lambda: service

    try:
        yield service, user
    finally:
        clear_overrides()


def test_transition_application_api_returns_public_status(
    authenticated_application_service,
) -> None:
    service, user = authenticated_application_service
    organization_id = uuid4()
    application_id = uuid4()
    now = datetime.now(UTC)

    service.transition_status_for_user.return_value = Application(
        id=application_id,
        organization_id=organization_id,
        job_id=uuid4(),
        candidate_id=uuid4(),
        status="screening",
        created_at=now,
        updated_at=now,
    )

    response = client.post(
        f"/organizations/{organization_id}/applications/{application_id}/transitions",
        json={"status": "screening"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "screening"
    assert response.json()["id"] == str(application_id)

    invocation = service.transition_status_for_user.await_args

    assert invocation.args[0] == application_id
    assert invocation.args[1].status is ApplicationStatus.SCREENING
    assert invocation.kwargs == {
        "organization_id": organization_id,
        "user_id": user.id,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "unknown"},
        {"status": None},
        {"status": "screening", "organization_id": str(uuid4())},
    ],
)
def test_transition_application_api_rejects_invalid_body(
    authenticated_application_service, payload: dict
) -> None:
    service, _ = authenticated_application_service

    response = client.post(
        f"/organizations/{uuid4()}/applications/{uuid4()}/transitions",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    service.transition_status_for_user.assert_not_awaited()


def test_transition_application_api_returns_business_conflict(
    authenticated_application_service,
) -> None:
    service, _ = authenticated_application_service

    details = {
        "current_status": "applied",
        "requested_status": "hired",
        "allowed_statuses": ["rejected", "screening"],
    }

    service.transition_status_for_user.side_effect = ConflictError(
        code="INVALID_APPLICATION_STATUS_TRANSITION",
        message="Application status transition is not allowed.",
        details=details,
    )

    response = client.post(
        f"/organizations/{uuid4()}/applications/{uuid4()}/transitions",
        json={"status": "hired"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_APPLICATION_STATUS_TRANSITION"
    assert response.json()["error"]["details"] == details


@pytest.mark.parametrize("code", ["ORGANIZATION_NOT_FOUND", "APPLICATION_NOT_FOUND"])
def test_transition_application_api_returns_scoped_not_found(
    authenticated_application_service, code: str
) -> None:
    service, _ = authenticated_application_service

    service.transition_status_for_user.side_effect = NotFoundError(
        code=code, message="Resource was not found."
    )

    response = client.post(
        f"/organizations/{uuid4()}/applications/{uuid4()}/transitions",
        json={"status": "screening"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == code


def test_transition_application_api_requires_authentication() -> None:
    response = client.post(
        f"/organizations/{uuid4()}/applications/{uuid4()}/transitions",
        json={"status": "screening"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"


def test_create_application_api_rejects_injected_status(
    authenticated_application_service,
) -> None:
    service, _ = authenticated_application_service

    response = client.post(
        f"/organizations/{uuid4()}/applications",
        json={
            "job_id": str(uuid4()),
            "candidate_id": str(uuid4()),
            "status": "hired",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    service.create.assert_not_awaited()
