from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.organizations import router as organization_router
from app.api.routes.users import router as user_router

api_router = APIRouter()


api_router.include_router(
    health_router,
)

api_router.include_router(
    organization_router,
)

api_router.include_router(
    user_router,
)

api_router.include_router(
    auth_router,
)
