import logging

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging

settings = get_settings()

configure_logging(level=settings.log_level)

logger = logging.getLogger("agenthire.api")
logger.info("application_configured")

app = FastAPI(
    title=settings.app_name,
    description="Backend API for AgentHire OS.",
    version=settings.app_version,
    debug=settings.debug,
)

register_exception_handlers(app)

app.include_router(api_router)
