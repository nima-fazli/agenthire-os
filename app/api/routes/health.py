from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(
    tags=["system"],
)

settings = get_settings()


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "agenthire-api",
        "version": settings.app_version,
    }
