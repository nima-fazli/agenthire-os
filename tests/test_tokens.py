from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.core.config import Settings
from app.core.tokens import (
    InvalidAccessTokenError,
    create_access_token,
    decode_access_token,
)


def build_test_settings(
    *,
    secret: str = "test-jwt-secret-that-is-long-enough",
) -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret=secret,
        jwt_algorithm="HS256",
        access_token_expire_minutes=30,
    )


def test_access_token_round_trip() -> None:
    settings = build_test_settings()

    user_id = uuid4()

    token = create_access_token(
        subject=user_id,
        settings=settings,
    )

    decoded_user_id = decode_access_token(
        token,
        settings=settings,
    )

    assert decoded_user_id == user_id


def test_access_token_contains_required_claims() -> None:
    settings = build_test_settings()

    user_id = uuid4()

    token = create_access_token(
        subject=user_id,
        settings=settings,
    )

    payload = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[
            settings.jwt_algorithm,
        ],
    )

    assert payload["sub"] == str(user_id)
    assert "iat" in payload
    assert "exp" in payload


def test_access_token_rejects_expired_token() -> None:
    settings = build_test_settings()

    old_time = datetime.now(UTC) - timedelta(
        hours=1
    )

    token = create_access_token(
        subject=uuid4(),
        settings=settings,
        now=old_time,
    )

    with pytest.raises(
        InvalidAccessTokenError
    ):
        decode_access_token(
            token,
            settings=settings,
        )


def test_access_token_rejects_wrong_signature() -> None:
    signing_settings = build_test_settings(
        secret="first-test-secret-that-is-long-enough",
    )

    verification_settings = build_test_settings(
        secret="second-test-secret-that-is-long-enough",
    )

    token = create_access_token(
        subject=uuid4(),
        settings=signing_settings,
    )

    with pytest.raises(
        InvalidAccessTokenError
    ):
        decode_access_token(
            token,
            settings=verification_settings,
        )


def test_access_token_rejects_invalid_subject() -> None:
    settings = build_test_settings()

    now = datetime.now(UTC)

    token = jwt.encode(
        {
            "sub": "not-a-valid-uuid",
            "iat": now,
            "exp": now + timedelta(
                minutes=30
            ),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(
        InvalidAccessTokenError
    ):
        decode_access_token(
            token,
            settings=settings,
        )
