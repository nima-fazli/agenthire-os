from fastapi import FastAPI

from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Backend API for AgentHire OS.",
    version=settings.app_version,
    debug=settings.debug,
)


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "agenthire-api",
        "version": settings.app_version,
    }
