from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_user_service
from app.core.errors import ConflictError
from app.main import app
from app.models.user import User
from app.services.user import UserService

client = TestClient(app)


@pytest.fixture
def user_service() -> Iterator[AsyncMock]:
    service = AsyncMock(
        spec=UserService
    )

    app.dependency_overrides[
        get_user_service
    ] = lambda: service

    try:
        yield service
    finally:
        app.dependency_overrides.pop(
            get_user_service,
            None,
        )


def test_register_user_api(
    user_service: AsyncMock,
) -> None:
    user_id = uuid4()
    now = datetime.now(UTC)

    user_service.create.return_value = User(
        id=user_id,
        email="nima@example.com",
        password_hash="hashed-secret",
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    response = client.post(
        "/users/register",
        json={
            "email": "  NIMA@EXAMPLE.COM  ",
            "password": "a-very-secure-password",
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body["id"] == str(user_id)
    assert body["email"] == "nima@example.com"
    assert body["is_active"] is True

    assert "password" not in body
    assert "password_hash" not in body

    user_service.create.assert_awaited_once()

    data = user_service.create.await_args.args[0]

    assert data.email == "nima@example.com"
    assert (
        data.password.get_secret_value()
        == "a-very-secure-password"
    )


def test_register_user_api_returns_conflict(
    user_service: AsyncMock,
) -> None:
    user_service.create.side_effect = ConflictError(
        code="USER_EMAIL_ALREADY_EXISTS",
        message="User email already exists.",
        details={
            "email": "nima@example.com",
        },
    )

    response = client.post(
        "/users/register",
        json={
            "email": "nima@example.com",
            "password": "a-very-secure-password",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "USER_EMAIL_ALREADY_EXISTS",
            "message": "User email already exists.",
            "details": {
                "email": "nima@example.com",
            },
        }
    }


def test_register_user_api_rejects_short_password(
    user_service: AsyncMock,
) -> None:
    response = client.post(
        "/users/register",
        json={
            "email": "nima@example.com",
            "password": "short",
        },
    )

    assert response.status_code == 422

    user_service.create.assert_not_awaited()
