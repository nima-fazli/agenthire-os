import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.api.dependencies import get_current_user
from app.core.errors import UnauthorizedError
from app.core.tokens import InvalidAccessTokenError
from app.models.user import User
from app.services.user import UserService


def build_credentials() -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="test-access-token",
    )


def test_get_current_user_returns_active_user() -> None:
    user_id = uuid4()

    user = User(
        id=user_id,
        email="nima@example.com",
        password_hash="hashed-secret",
        is_active=True,
    )

    service = AsyncMock(
        spec=UserService
    )
    service.get_by_id.return_value = user

    with patch(
        "app.api.dependencies.decode_access_token",
        return_value=user_id,
    ) as token_decoder:
        result = asyncio.run(
            get_current_user(
                credentials=build_credentials(),
                service=service,
            )
        )

    assert result is user

    token_decoder.assert_called_once_with(
        "test-access-token"
    )
    service.get_by_id.assert_awaited_once_with(
        user_id
    )


def test_get_current_user_rejects_missing_credentials() -> None:
    service = AsyncMock(
        spec=UserService
    )

    with pytest.raises(
        UnauthorizedError
    ) as error:
        asyncio.run(
            get_current_user(
                credentials=None,
                service=service,
            )
        )

    assert error.value.status_code == 401
    assert error.value.code == "INVALID_ACCESS_TOKEN"

    service.get_by_id.assert_not_awaited()


def test_get_current_user_rejects_invalid_token() -> None:
    service = AsyncMock(
        spec=UserService
    )

    with (
        patch(
            "app.api.dependencies.decode_access_token",
            side_effect=InvalidAccessTokenError(
                "Invalid access token."
            ),
        ),
        pytest.raises(UnauthorizedError) as error,
    ):
        asyncio.run(
            get_current_user(
                credentials=build_credentials(),
                service=service,
            )
        )

    assert error.value.status_code == 401
    assert error.value.code == "INVALID_ACCESS_TOKEN"

    service.get_by_id.assert_not_awaited()


def test_get_current_user_rejects_missing_user() -> None:
    user_id = uuid4()

    service = AsyncMock(
        spec=UserService
    )
    service.get_by_id.return_value = None

    with (
        patch(
            "app.api.dependencies.decode_access_token",
            return_value=user_id,
        ),
        pytest.raises(UnauthorizedError) as error,
    ):
        asyncio.run(
            get_current_user(
                credentials=build_credentials(),
                service=service,
            )
        )

    assert error.value.status_code == 401
    assert error.value.code == "INVALID_ACCESS_TOKEN"


def test_get_current_user_rejects_inactive_user() -> None:
    user_id = uuid4()

    user = User(
        id=user_id,
        email="nima@example.com",
        password_hash="hashed-secret",
        is_active=False,
    )

    service = AsyncMock(
        spec=UserService
    )
    service.get_by_id.return_value = user

    with (
        patch(
            "app.api.dependencies.decode_access_token",
            return_value=user_id,
        ),
        pytest.raises(UnauthorizedError) as error,
    ):
        asyncio.run(
            get_current_user(
                credentials=build_credentials(),
                service=service,
            )
        )

    assert error.value.status_code == 401
    assert error.value.code == "INVALID_ACCESS_TOKEN"
