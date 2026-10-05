from collections.abc import AsyncIterator

from fastapi import Depends, Security
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from app.core.errors import UnauthorizedError
from app.core.tokens import (
    InvalidAccessTokenError,
    decode_access_token,
)
from app.db.session import get_db_session
from app.models.user import User
from app.services.organization import OrganizationService
from app.services.user import UserService

bearer_scheme = HTTPBearer(
    auto_error=False,
)


async def get_organization_service() -> AsyncIterator[OrganizationService]:
    async for session in get_db_session():
        yield OrganizationService(session)


async def get_user_service() -> AsyncIterator[UserService]:
    async for session in get_db_session():
        yield UserService(session)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(
        bearer_scheme
    ),
    service: UserService = Depends(
        get_user_service
    ),
) -> User:
    if credentials is None:
        raise _invalid_access_token_error()

    try:
        user_id = decode_access_token(
            credentials.credentials
        )
    except InvalidAccessTokenError as error:
        raise _invalid_access_token_error() from error

    user = await service.get_by_id(
        user_id
    )

    if (
        user is None
        or not user.is_active
    ):
        raise _invalid_access_token_error()

    return user


def _invalid_access_token_error() -> UnauthorizedError:
    return UnauthorizedError(
        code="INVALID_ACCESS_TOKEN",
        message="Access token is invalid or missing.",
    )
