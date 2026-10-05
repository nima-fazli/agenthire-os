from fastapi import APIRouter, Depends, status

from app.api.dependencies import (
    get_current_user,
    get_user_service,
)
from app.models.user import User
from app.schemas.user import UserCreate, UserRead
from app.services.user import UserService

router = APIRouter(
    prefix="/users",
    tags=["users"],
)


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    data: UserCreate,
    service: UserService = Depends(
        get_user_service,
    ),
) -> UserRead:
    user = await service.create(data)

    return UserRead.model_validate(
        user,
    )


@router.get(
    "/me",
    response_model=UserRead,
)
async def get_me(
    current_user: User = Depends(
        get_current_user,
    ),
) -> UserRead:
    return UserRead.model_validate(
        current_user,
    )
