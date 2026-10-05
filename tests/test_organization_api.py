from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_organization_service
from app.core.errors import ConflictError
from app.main import app
from app.models.organization import Organization
from app.services.organization import OrganizationService

client = TestClient(app)


@pytest.fixture
def organization_service() -> Iterator[AsyncMock]:
    service = AsyncMock(spec=OrganizationService)

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
