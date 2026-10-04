from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Backend API for AgentHire OS.",
    version=settings.app_version,
    debug=settings.debug,
)

app.include_router(api_router)
