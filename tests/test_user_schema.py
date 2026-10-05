from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.user import UserCreate, UserRead


def test_user_create_normalizes_email() -> None:
    user = UserCreate(
        email="  NIMA@EXAMPLE.COM  ",
        password="a-very-secure-password",
    )

    assert user.email == "nima@example.com"


def test_user_create_rejects_short_password() -> None:
    with pytest.raises(ValidationError):
        UserCreate(
            email="nima@example.com",
            password="short",
        )


def test_user_create_hides_password_value() -> None:
    user = UserCreate(
        email="nima@example.com",
        password="a-very-secure-password",
    )

    assert "a-very-secure-password" not in repr(user)


def test_user_read_does_not_expose_password_hash() -> None:
    now = datetime.now(UTC)

    source = SimpleNamespace(
        id=uuid4(),
        email="nima@example.com",
        password_hash="hashed-secret",
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    user = UserRead.model_validate(source)

    body = user.model_dump()

    assert body["email"] == "nima@example.com"
    assert "password_hash" not in body
