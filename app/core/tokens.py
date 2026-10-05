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
