from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings

router = APIRouter(tags=["system"])
settings = get_settings()


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "agenthire-api",
        "version": settings.app_version,
    }


@router.get("/ready", responses={503: {"description": "Core API dependencies unavailable"}})
async def readiness_check(request: Request) -> JSONResponse:
    probe = getattr(request.app.state, "readiness", None)
    ready = probe is not None and (await probe.snapshot()).ready
    return JSONResponse(
        {"status": "ready" if ready else "not_ready"},
        status_code=200 if ready else 503,
        headers={"Cache-Control": "no-store"},
    )
