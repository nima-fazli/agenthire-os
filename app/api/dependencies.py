from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Depends, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.tokens import InvalidAccessTokenError, decode_session_token
from app.db.session import get_db_session
from app.models.user import User
from app.services.access import AccessService
from app.services.organization import OrganizationService
from app.services.sessions import SessionService, invalid_token
from app.services.user import UserService

bearer_scheme = HTTPBearer(auto_error=False)


async def get_organization_service() -> AsyncIterator[OrganizationService]:
    async for session in get_db_session():
        yield OrganizationService(session)


async def get_user_service() -> AsyncIterator[UserService]:
    async for session in get_db_session():
        yield UserService(session)


def get_session_service(session=Depends(get_db_session)):
    return SessionService(session)


def get_access_service(session=Depends(get_db_session)):
    return AccessService(session)


async def get_current_user(
    request: Request, response: Response,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    service: SessionService = Depends(get_session_service),
) -> User:
    if credentials is None:
        raise invalid_token()
    try:
        claims = decode_session_token(credentials.credentials)
    except InvalidAccessTokenError as error:
        raise invalid_token() from error
    user = await service.validate(claims)
    request.state.session_id = claims.session_id
    response.headers["Cache-Control"] = "private, no-store"
    organization_id = request.path_params.get("organization_id")
    if organization_id is not None:
        try:
            organization_id = UUID(str(organization_id))
        except ValueError:
            return user  # FastAPI still returns the normal path-validation 422.
        await AccessService(service.session).authorize(organization_id, user.id, request.method, request.url.path)
    return user
