import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.readiness import StorageProbe, expected_migration_heads
from app.core.request_observability import RequestObservabilityMiddleware
from app.db.session import async_session_factory, engine
from app.services.runtime_health import RuntimeReadiness
from app.web.router import public_router as agents_ui_router
from app.web.router import router as recruiter_ui_router

settings = get_settings()
configure_logging(level=settings.log_level)
logger = logging.getLogger("agenthire.api")
logger.info("application_configured")


@asynccontextmanager
async def lifespan(application: FastAPI):
    probe = RuntimeReadiness(
        async_session_factory,
        StorageProbe(settings.document_storage_path),
        expected_migration_heads(),
    )
    application.state.readiness = probe
    try:
        yield
    finally:
        await probe.close()
        await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="Recruiting API and private recruiter workspace for AgentHire OS.",
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)
app.add_middleware(RequestObservabilityMiddleware)
register_exception_handlers(app)
app.include_router(api_router)
app.include_router(recruiter_ui_router)

app.include_router(agents_ui_router)
