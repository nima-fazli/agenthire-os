from collections.abc import Iterator
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_user_service
from app.core.errors import UnauthorizedError
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


def test_login_returns_access_token(
    user_service: AsyncMock,
) -> None:
    user_id = uuid4()

    user_service.authenticate.return_value = User(
        id=user_id,
        email="nima@example.com",
        password_hash="hashed-secret",
        is_active=True,
    )

    with patch(
        "app.api.routes.auth.create_access_token",
        return_value="test-access-token",
    ) as token_creator:
        response = client.post(
            "/auth/login",
            json={
                "email": "  NIMA@EXAMPLE.COM  ",
                "password": "a-very-secure-password",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "test-access-token",
        "token_type": "bearer",
    }

    user_service.authenticate.assert_awaited_once_with(
        email="nima@example.com",
        password="a-very-secure-password",
    )

    token_creator.assert_called_once_with(
        subject=user_id,
    )


def test_login_rejects_invalid_credentials(
    user_service: AsyncMock,
) -> None:
    user_service.authenticate.side_effect = (
        UnauthorizedError(
            code="INVALID_CREDENTIALS",
            message="Invalid email or password.",
        )
    )

    with patch(
        "app.api.routes.auth.create_access_token"
    ) as token_creator:
        response = client.post(
            "/auth/login",
            json={
                "email": "nima@example.com",
                "password": "wrong-password",
            },
        )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "INVALID_CREDENTIALS",
            "message": "Invalid email or password.",
            "details": {},
        }
    }

    token_creator.assert_not_called()


def test_login_rejects_empty_password(
    user_service: AsyncMock,
) -> None:
    response = client.post(
        "/auth/login",
        json={
            "email": "nima@example.com",
            "password": "",
        },
    )

    assert response.status_code == 422

    user_service.authenticate.assert_not_awaited()
