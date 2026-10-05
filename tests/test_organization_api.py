from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_organization_service
from app.core.errors import ConflictError, NotFoundError
from app.main import app
from app.models.organization import Organization
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


async def fake_create(data):
    now = datetime.now(UTC)

    return Organization(
        id=uuid4(),
        name=data.name,
        slug=data.slug,
        created_at=now,
        updated_at=now,
    )


def test_create_organization_api(
    organization_service: AsyncMock,
) -> None:
    organization_service.create.side_effect = fake_create

    response = client.post(
        "/organizations",
        json={
            "name": "Acme Corporation",
            "slug": "acme",
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body["name"] == "Acme Corporation"
    assert body["slug"] == "acme"


def test_create_organization_api_returns_conflict(
    organization_service: AsyncMock,
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
            "name": "Acme Corporation",
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


def test_get_organization_api(
    organization_service: AsyncMock,
) -> None:
    organization_id = uuid4()
    now = datetime.now(UTC)

    organization_service.get_by_id.return_value = (
        Organization(
            id=organization_id,
            name="Acme Corporation",
            slug="acme",
            created_at=now,
            updated_at=now,
        )
    )

    response = client.get(
        f"/organizations/{organization_id}"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["id"] == str(
        organization_id
    )
    assert body["name"] == "Acme Corporation"
    assert body["slug"] == "acme"

    organization_service.get_by_id.assert_awaited_once_with(
        organization_id
    )


def test_get_organization_api_returns_not_found(
    organization_service: AsyncMock,
) -> None:
    organization_id = uuid4()

    organization_service.get_by_id.side_effect = (
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

    organization_service.get_by_id.assert_awaited_once_with(
        organization_id
    )
