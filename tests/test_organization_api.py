from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_current_user,
    get_organization_service,
)
from app.core.errors import (
    ConflictError,
    NotFoundError,
    UnauthorizedError,
)
from app.main import app
from app.models.organization import Organization
from app.models.user import User
from app.services.organization import OrganizationService

client = TestClient(app)


@pytest.fixture
def organization_service() -> Iterator[AsyncMock]:
    service = AsyncMock(
        spec=OrganizationService
    )

    app.dependency_overrides[
        get_organization_service
    ] = lambda: service

    try:
        yield service
    finally:
        app.dependency_overrides.pop(
            get_organization_service,
            None,
        )


@pytest.fixture
def authenticated_user() -> Iterator[User]:
    user = User(
        id=uuid4(),
        email="nima@example.com",
        password_hash="hashed-secret",
        is_active=True,
    )

    app.dependency_overrides[
        get_current_user
    ] = lambda: user

    try:
        yield user
    finally:
        app.dependency_overrides.pop(
            get_current_user,
            None,
        )


def test_create_organization_api(
    organization_service: AsyncMock,
    authenticated_user: User,
) -> None:
    organization_id = uuid4()
    now = datetime.now(UTC)

    organization_service.create.return_value = Organization(
        id=organization_id,
        name="Acme",
        slug="acme",
        created_at=now,
        updated_at=now,
    )

    response = client.post(
        "/organizations",
        json={
            "name": " Acme ",
            "slug": " ACME ",
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body["id"] == str(
        organization_id
    )
    assert body["name"] == "Acme"
    assert body["slug"] == "acme"

    organization_service.create.assert_awaited_once()

    call = organization_service.create.await_args

    data = call.args[0]

    assert data.name == "Acme"
    assert data.slug == "acme"

    assert call.kwargs == {
        "owner_user_id": authenticated_user.id,
    }


def test_create_organization_api_requires_authentication(
    organization_service: AsyncMock,
) -> None:
    def reject_current_user() -> None:
        raise UnauthorizedError(
            code="INVALID_ACCESS_TOKEN",
            message="Access token is invalid or missing.",
        )

    app.dependency_overrides[
        get_current_user
    ] = reject_current_user

    try:
        response = client.post(
            "/organizations",
            json={
                "name": "Acme",
                "slug": "acme",
            },
        )
    finally:
        app.dependency_overrides.pop(
            get_current_user,
            None,
        )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "INVALID_ACCESS_TOKEN",
            "message": "Access token is invalid or missing.",
            "details": {},
        }
    }

    organization_service.create.assert_not_awaited()


def test_create_organization_api_returns_conflict(
    organization_service: AsyncMock,
    authenticated_user: User,
) -> None:
    organization_service.create.side_effect = ConflictError(
        code="ORGANIZATION_SLUG_ALREADY_EXISTS",
        message="Organization slug already exists.",
        details={
            "slug": "acme",
        },
    )

    response = client.post(
        "/organizations",
        json={
            "name": "Acme",
            "slug": "acme",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "ORGANIZATION_SLUG_ALREADY_EXISTS",
            "message": "Organization slug already exists.",
            "details": {
                "slug": "acme",
            },
        }
    }

    organization_service.create.assert_awaited_once()

    call = organization_service.create.await_args

    assert call.kwargs == {
        "owner_user_id": authenticated_user.id,
    }


def test_get_organization_api(
    organization_service: AsyncMock,
) -> None:
    organization_id = uuid4()
    now = datetime.now(UTC)

    organization_service.get_by_id.return_value = Organization(
        id=organization_id,
        name="Acme",
        slug="acme",
        created_at=now,
        updated_at=now,
    )

    response = client.get(
        f"/organizations/{organization_id}"
    )

    assert response.status_code == 200

    assert response.json() == {
        "id": str(
            organization_id
        ),
        "name": "Acme",
        "slug": "acme",
        "created_at": now.isoformat().replace(
            "+00:00",
            "Z",
        ),
        "updated_at": now.isoformat().replace(
            "+00:00",
            "Z",
        ),
    }

    organization_service.get_by_id.assert_awaited_once_with(
        organization_id
    )


def test_get_organization_api_returns_not_found(
    organization_service: AsyncMock,
) -> None:
    organization_id = uuid4()

    organization_service.get_by_id.side_effect = NotFoundError(
        code="ORGANIZATION_NOT_FOUND",
        message="Organization was not found.",
        details={
            "organization_id": str(
                organization_id
            ),
        },
    )

    response = client.get(
        f"/organizations/{organization_id}"
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "ORGANIZATION_NOT_FOUND",
            "message": "Organization was not found.",
            "details": {
                "organization_id": str(
                    organization_id
                ),
            },
        }
    }
