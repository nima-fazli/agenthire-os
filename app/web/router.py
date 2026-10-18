from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(prefix="/workspace", include_in_schema=False)
ASSET_ROOT = Path(__file__).resolve().parent / "assets"
ASSETS = {
    "index.html": "text/html",
    "styles.css": "text/css",
    **{f"{name}.mjs": "text/javascript" for name in (
        "app", "api", "session", "requests", "dom", "workspace",
        "profiles", "candidates", "evidence", "notifications",
        "paging", "confirmation", "editors", "applications", "documents",
    )},
}
UI_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self'; font-src 'self'; "
        "base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
}


def asset_response(filename: str):
    path = ASSET_ROOT / filename
    try:
        valid = (
            filename in ASSETS and not path.is_symlink() and path.is_file()
            and path.resolve().parent == ASSET_ROOT.resolve() and path.stat().st_size > 0
        )
    except OSError:
        valid = False
    if not valid:
        return JSONResponse(
            {"error": {"code": "UI_ASSET_NOT_FOUND", "message": "Asset not found.", "details": {}}},
            status_code=404, headers=UI_HEADERS,
        )
    return FileResponse(path, media_type=ASSETS[filename], headers=UI_HEADERS)


@router.api_route("", methods=["GET", "HEAD"])
@router.api_route("/", methods=["GET", "HEAD"])
async def workspace():
    return asset_response("index.html")


@router.api_route("/assets/{filename}", methods=["GET", "HEAD"])
async def asset(filename: str):
    return asset_response(filename)
