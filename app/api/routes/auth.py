from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import get_current_user, get_session_service
from app.api.routes.access import router as access_router
from app.schemas.access import (
    LoginResponse,
    PasswordChange,
    PasswordConfirmation,
    SessionRead,
)
from app.schemas.auth import LoginRequest


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


auth_router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(private_response)])


@auth_router.post("/login", response_model=LoginResponse)
async def login(data: LoginRequest, service=Depends(get_session_service)):
    return await service.login(data)


@auth_router.get("/sessions", response_model=list[SessionRead])
async def sessions(request: Request, user=Depends(get_current_user), service=Depends(get_session_service)):
    return await service.list(user.id, request.state.session_id)


@auth_router.post("/logout", status_code=204)
async def logout(request: Request, user=Depends(get_current_user), service=Depends(get_session_service)):
    await service.logout(user.id, request.state.session_id)


@auth_router.post("/sessions/revoke-others", status_code=204)
async def revoke_others(request: Request, data: PasswordConfirmation,
                       user=Depends(get_current_user), service=Depends(get_session_service)):
    await service.revoke(user, request.state.session_id, data.current_password.get_secret_value())


@auth_router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(session_id: UUID, request: Request, data: PasswordConfirmation,
                         user=Depends(get_current_user), service=Depends(get_session_service)):
    await service.revoke(user, request.state.session_id, data.current_password.get_secret_value(), session_id)


@auth_router.put("/password", status_code=204)
async def change_password(data: PasswordChange, user=Depends(get_current_user), service=Depends(get_session_service)):
    await service.change_password(user, data)


router = APIRouter()
router.include_router(auth_router)
router.include_router(access_router)
