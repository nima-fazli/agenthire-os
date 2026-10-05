from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_organization_service
from app.main import app
from app.models.organization import Organization

client = TestClient(app)


async def fake_create(data):
    now = datetime.now(UTC)

    return Organization(
        id=uuid4(),
        name=data.name,
        slug=data.slug,
        created_at=now,
        updated_at=now,
    )


def test_create_organization_api() -> None:
    service = AsyncMock()

    service.create.side_effect = fake_create

    app.dependency_overrides[
        get_organization_service
    ] = lambda: service

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

    app.dependency_overrides.clear()
