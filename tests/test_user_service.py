import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import hash_password
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate
from app.services.user import UserService


def test_create_user_hashes_password_and_commits() -> None:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    repository = MagicMock(
        spec=UserRepository
    )

    repository.get_by_email.return_value = None

    user = User(
        email="nima@example.com",
        password_hash="hashed-secret",
    )

    repository.create.return_value = user

    service = UserService(session)
    service._repository = repository

    with patch(
        "app.services.user.hash_password",
        return_value="hashed-secret",
    ) as password_hasher:
        result = asyncio.run(
            service.create(
                UserCreate(
                    email="NIMA@EXAMPLE.COM",
                    password="a-very-secure-password",
                )
            )
        )

    assert result is user

    repository.get_by_email.assert_called_once_with(
        "nima@example.com"
    )

    password_hasher.assert_called_once_with(
        "a-very-secure-password"
    )

    repository.create.assert_called_once_with(
        email="nima@example.com",
        password_hash="hashed-secret",
    )

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


def test_create_user_rejects_duplicate_email() -> None:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    repository = MagicMock(
        spec=UserRepository
    )

    repository.get_by_email.return_value = User(
        email="nima@example.com",
        password_hash="existing-hash",
    )

    service = UserService(session)
    service._repository = repository

    with (
        patch(
            "app.services.user.hash_password"
        ) as password_hasher,
        pytest.raises(ConflictError) as error,
    ):
        asyncio.run(
            service.create(
                UserCreate(
                    email="nima@example.com",
                    password="a-very-secure-password",
                )
            )
        )

    assert error.value.status_code == 409
    assert (
        error.value.code
        == "USER_EMAIL_ALREADY_EXISTS"
    )
    assert error.value.details == {
        "email": "nima@example.com",
    }

    password_hasher.assert_not_called()
    repository.create.assert_not_called()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


def test_create_user_handles_concurrent_duplicate_email() -> None:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    repository = MagicMock(
        spec=UserRepository
    )

    repository.get_by_email.side_effect = [
        None,
        User(
            email="nima@example.com",
            password_hash="existing-hash",
        ),
    ]

    repository.create.side_effect = IntegrityError(
        "INSERT INTO users ...",
        {},
        Exception("duplicate key"),
    )

    service = UserService(session)
    service._repository = repository

    with (
        patch(
            "app.services.user.hash_password",
            return_value="hashed-secret",
        ),
        pytest.raises(ConflictError) as error,
    ):
        asyncio.run(
            service.create(
                UserCreate(
                    email="nima@example.com",
                    password="a-very-secure-password",
                )
            )
        )

    assert error.value.status_code == 409
    assert (
        error.value.code
        == "USER_EMAIL_ALREADY_EXISTS"
    )

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_create_user_reraises_unrelated_integrity_error() -> None:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    repository = MagicMock(
        spec=UserRepository
    )

    integrity_error = IntegrityError(
        "INSERT INTO users ...",
        {},
        Exception("different integrity failure"),
    )

    repository.get_by_email.side_effect = [
        None,
        None,
    ]

    repository.create.side_effect = integrity_error

    service = UserService(session)
    service._repository = repository

    with (
        patch(
            "app.services.user.hash_password",
            return_value="hashed-secret",
        ),
        pytest.raises(IntegrityError) as error,
    ):
        asyncio.run(
            service.create(
                UserCreate(
                    email="nima@example.com",
                    password="a-very-secure-password",
                )
            )
        )

    assert error.value is integrity_error

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_authenticate_user_with_valid_credentials() -> None:
    session = MagicMock(spec=AsyncSession)

    password = "a-very-secure-password"

    user = User(
        email="nima@example.com",
        password_hash=hash_password(
            password
        ),
        is_active=True,
    )

    repository = MagicMock(
        spec=UserRepository
    )
    repository.get_by_email.return_value = user

    service = UserService(session)
    service._repository = repository

    result = asyncio.run(
        service.authenticate(
            email="nima@example.com",
            password=password,
        )
    )

    assert result is user

    repository.get_by_email.assert_called_once_with(
        "nima@example.com"
    )


def test_authenticate_user_rejects_wrong_password() -> None:
    session = MagicMock(spec=AsyncSession)

    user = User(
        email="nima@example.com",
        password_hash=hash_password(
            "a-very-secure-password"
        ),
        is_active=True,
    )

    repository = MagicMock(
        spec=UserRepository
    )
    repository.get_by_email.return_value = user

    service = UserService(session)
    service._repository = repository

    with pytest.raises(
        UnauthorizedError
    ) as error:
        asyncio.run(
            service.authenticate(
                email="nima@example.com",
                password="wrong-password",
            )
        )

    assert error.value.status_code == 401
    assert error.value.code == "INVALID_CREDENTIALS"
    assert error.value.details == {}


def test_authenticate_user_rejects_unknown_email() -> None:
    session = MagicMock(spec=AsyncSession)

    repository = MagicMock(
        spec=UserRepository
    )
    repository.get_by_email.return_value = None

    service = UserService(session)
    service._repository = repository

    with pytest.raises(
        UnauthorizedError
    ) as error:
        asyncio.run(
            service.authenticate(
                email="missing@example.com",
                password="a-very-secure-password",
            )
        )

    assert error.value.status_code == 401
    assert error.value.code == "INVALID_CREDENTIALS"


def test_authenticate_user_rejects_inactive_user() -> None:
    session = MagicMock(spec=AsyncSession)

    password = "a-very-secure-password"

    user = User(
        email="nima@example.com",
        password_hash=hash_password(
            password
        ),
        is_active=False,
    )

    repository = MagicMock(
        spec=UserRepository
    )
    repository.get_by_email.return_value = user

    service = UserService(session)
    service._repository = repository

    with pytest.raises(
        UnauthorizedError
    ) as error:
        asyncio.run(
            service.authenticate(
                email="nima@example.com",
                password=password,
            )
        )

    assert error.value.status_code == 401
    assert error.value.code == "INVALID_CREDENTIALS"
