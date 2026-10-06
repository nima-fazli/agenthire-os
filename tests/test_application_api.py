from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes.applications import (
    get_application_service,
)
from app.core.errors import ConflictError, NotFoundError
from app.main import app
from app.models.application import Application
from app.models.user import User
from app.services.application import ApplicationService

client = TestClient(
    app
)


def make_user() -> User:
    return User(
        id=uuid4(),
        email="recruiter@example.com",
        password_hash="hashed-secret",
        is_active=True,
    )


def override_authenticated_user(
    user: User,
) -> None:
    app.dependency_overrides[
        get_current_user
    ] = lambda: user


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_create_application_api() -> None:
    user = make_user()
    organization_id = uuid4()
    job_id = uuid4()
    candidate_id = uuid4()
    application_id = uuid4()
    now = datetime.now(UTC)

    service = AsyncMock(
        spec=ApplicationService
    )

    service.create.return_value = Application(
        id=application_id,
        organization_id=organization_id,
        job_id=job_id,
        candidate_id=candidate_id,
        created_at=now,
        updated_at=now,
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_application_service
    ] = lambda: service

    try:
        response = client.post(
            (
                f"/organizations/{organization_id}"
                "/applications"
            ),
            json={
                "job_id": str(
                    job_id
                ),
                "candidate_id": str(
                    candidate_id
                ),
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201

    body = response.json()

    assert body["id"] == str(
        application_id
    )
    assert body["job_id"] == str(
        job_id
    )
    assert body["candidate_id"] == str(
        candidate_id
    )

    call = service.create.await_args

    data = call.args[0]

    assert data.job_id == job_id
    assert data.candidate_id == candidate_id

    assert call.kwargs == {
        "organization_id": organization_id,
        "user_id": user.id,
    }


def test_create_application_api_returns_duplicate_conflict() -> None:
    user = make_user()
    organization_id = uuid4()
    job_id = uuid4()
    candidate_id = uuid4()

    service = AsyncMock(
        spec=ApplicationService
    )

    service.create.side_effect = ConflictError(
        code="APPLICATION_ALREADY_EXISTS",
        message=(
            "Application already exists "
            "for this job and candidate."
        ),
        details={
            "organization_id": str(
                organization_id
            ),
            "job_id": str(
                job_id
            ),
            "candidate_id": str(
                candidate_id
            ),
        },
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_application_service
    ] = lambda: service

    try:
        response = client.post(
            (
                f"/organizations/{organization_id}"
                "/applications"
            ),
            json={
                "job_id": str(
                    job_id
                ),
                "candidate_id": str(
                    candidate_id
                ),
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 409

    assert (
        response.json()["error"]["code"]
        == "APPLICATION_ALREADY_EXISTS"
    )


def test_list_applications_api() -> None:
    user = make_user()
    organization_id = uuid4()
    now = datetime.now(UTC)

    service = AsyncMock(
        spec=ApplicationService
    )

    service.list_for_user.return_value = [
        Application(
            id=uuid4(),
            organization_id=organization_id,
            job_id=uuid4(),
            candidate_id=uuid4(),
            created_at=now,
            updated_at=now,
        ),
        Application(
            id=uuid4(),
            organization_id=organization_id,
            job_id=uuid4(),
            candidate_id=uuid4(),
            created_at=now,
            updated_at=now,
        ),
    ]

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_application_service
    ] = lambda: service

    try:
        response = client.get(

                f"/organizations/{organization_id}"
                "/applications"

        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_application_api() -> None:
    user = make_user()
    organization_id = uuid4()
    application_id = uuid4()
    now = datetime.now(UTC)

    service = AsyncMock(
        spec=ApplicationService
    )

    service.get_for_user.return_value = Application(
        id=application_id,
        organization_id=organization_id,
        job_id=uuid4(),
        candidate_id=uuid4(),
        created_at=now,
        updated_at=now,
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_application_service
    ] = lambda: service

    try:
        response = client.get(

                f"/organizations/{organization_id}"
                f"/applications/{application_id}"

        )
    finally:
        clear_overrides()

    assert response.status_code == 200

    assert response.json()["id"] == str(
        application_id
    )


def test_get_application_api_returns_not_found() -> None:
    user = make_user()
    organization_id = uuid4()
    application_id = uuid4()

    service = AsyncMock(
        spec=ApplicationService
    )

    service.get_for_user.side_effect = (
        NotFoundError(
            code="APPLICATION_NOT_FOUND",
            message="Application was not found.",
            details={
                "organization_id": str(
                    organization_id
                ),
                "application_id": str(
                    application_id
                ),
            },
        )
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_application_service
    ] = lambda: service

    try:
        response = client.get(

                f"/organizations/{organization_id}"
                f"/applications/{application_id}"

        )
    finally:
        clear_overrides()

    assert response.status_code == 404

    assert (
        response.json()["error"]["code"]
        == "APPLICATION_NOT_FOUND"
    )


def test_application_api_hides_organization_from_non_member() -> None:
    user = make_user()
    organization_id = uuid4()

    service = AsyncMock(
        spec=ApplicationService
    )

    service.list_for_user.side_effect = (
        NotFoundError(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization was not found.",
            details={
                "organization_id": str(
                    organization_id
                ),
            },
        )
    )

    override_authenticated_user(
        user
    )

    app.dependency_overrides[
        get_application_service
    ] = lambda: service

    try:
        response = client.get(

                f"/organizations/{organization_id}"
                "/applications"

        )
    finally:
        clear_overrides()

    assert response.status_code == 404

    assert (
        response.json()["error"]["code"]
        == "ORGANIZATION_NOT_FOUND"
    )


def test_application_api_requires_authentication() -> None:
    organization_id = uuid4()

    response = client.get(

            f"/organizations/{organization_id}"
            "/applications"

    )

    assert response.status_code == 401

    assert (
        response.json()["error"]["code"]
        == "INVALID_ACCESS_TOKEN"
    )
