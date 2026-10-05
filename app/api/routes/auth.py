from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_user_service
from app.core.tokens import create_access_token
from app.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
)
from app.services.user import UserService

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


@router.post(
    "/login",
    response_model=AccessTokenResponse,
    status_code=status.HTTP_200_OK,
)
async def login(
    data: LoginRequest,
    service: UserService = Depends(
        get_user_service,
    ),
) -> AccessTokenResponse:
    user = await service.authenticate(
        email=data.email,
        password=data.password.get_secret_value(),
    )

    access_token = create_access_token(
        subject=user.id,
    )

    return AccessTokenResponse(
        access_token=access_token,
    )
