import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.user import UserRepository


def test_create_user_adds_flushes_and_refreshes_without_commit() -> None:
    session = MagicMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()

    repository = UserRepository(session)

    user = asyncio.run(
        repository.create(
            email="nima@example.com",
            password_hash="hashed-secret",
        )
    )

    assert user.email == "nima@example.com"
    assert user.password_hash == "hashed-secret"

    session.add.assert_called_once_with(user)
    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(user)
    session.commit.assert_not_awaited()


def test_get_user_by_id() -> None:
    session = MagicMock(spec=AsyncSession)

    user_id = uuid4()

    user = User(
        id=user_id,
        email="nima@example.com",
        password_hash="hashed-secret",
    )

    session.get = AsyncMock(
        return_value=user
    )

    repository = UserRepository(session)

    result = asyncio.run(
        repository.get_by_id(user_id)
    )

    assert result is user

    session.get.assert_awaited_once_with(
        User,
        user_id,
    )


def test_get_user_by_email() -> None:
    session = MagicMock(spec=AsyncSession)

    user = User(
        email="nima@example.com",
        password_hash="hashed-secret",
    )

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = user

    session.execute = AsyncMock(
        return_value=query_result
    )

    repository = UserRepository(session)

    result = asyncio.run(
        repository.get_by_email(
            "nima@example.com"
        )
    )

    assert result is user

    session.execute.assert_awaited_once()
    query_result.scalar_one_or_none.assert_called_once_with()
