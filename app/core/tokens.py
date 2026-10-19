from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from jwt import InvalidTokenError as PyJWTInvalidTokenError

from app.core.config import Settings, get_settings


class InvalidAccessTokenError(Exception):
    pass


def create_access_token(
    *,
    subject: UUID,
    session_id: UUID | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> str:
    resolved_settings = settings or get_settings()

    issued_at = now or datetime.now(UTC)

    expires_at = issued_at + timedelta(
        minutes=resolved_settings.access_token_expire_minutes
    )

    payload = {
        "sub": str(subject),
        "iat": issued_at,
        "exp": expires_at,
    }
    if session_id is not None:
        payload.update(sid=str(session_id), purpose="access", iss="agenthire-os", aud="agenthire-os")

    return jwt.encode(
        payload,
        resolved_settings.jwt_secret.get_secret_value(),
        algorithm=resolved_settings.jwt_algorithm,
    )


def decode_access_token(
    token: str,
    *,
    settings: Settings | None = None,
) -> UUID:
    resolved_settings = settings or get_settings()

    try:
        payload = jwt.decode(
            token,
            resolved_settings.jwt_secret.get_secret_value(),
            algorithms=[
                resolved_settings.jwt_algorithm,
            ],
            options={
                "verify_aud": False,
                "require": [
                    "sub",
                    "iat",
                    "exp",
                ],
            },
        )

        subject = payload["sub"]

        return UUID(subject)

    except (
        PyJWTInvalidTokenError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise InvalidAccessTokenError(
            "Invalid access token."
        ) from error


@dataclass(frozen=True)
class SessionClaims:
    user_id: UUID
    session_id: UUID
    expires_at: datetime


def decode_session_token(token: str, *, settings: Settings | None = None) -> SessionClaims:
    """Runtime authentication requires a tracked session; pre-stage-3 tokens fail closed."""
    resolved = settings or get_settings()
    try:
        payload = jwt.decode(
            token, resolved.jwt_secret.get_secret_value(), algorithms=[resolved.jwt_algorithm],
            issuer="agenthire-os", audience="agenthire-os",
            options={"require": ["sub", "sid", "iat", "exp", "iss", "aud", "purpose"], "strict_aud": True},
        )
        if payload["purpose"] != "access" or type(payload["exp"]) is not int or type(payload["iat"]) is not int:
            raise ValueError("Invalid token purpose or expiry.")
        return SessionClaims(UUID(payload["sub"]), UUID(payload["sid"]), datetime.fromtimestamp(payload["exp"], UTC))
    except (PyJWTInvalidTokenError, KeyError, TypeError, ValueError, OverflowError) as error:
        raise InvalidAccessTokenError("Invalid access token.") from error
