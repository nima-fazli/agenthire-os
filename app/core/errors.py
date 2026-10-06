import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("agenthire.errors")


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)

        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class ConflictError(AppError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            details=details,
        )


class NotFoundError(AppError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            details=details,
        )


class UnauthorizedError(AppError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            details=details,
        )


async def app_error_handler(
    _request: Request,
    exc: AppError,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


async def request_validation_error_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = [
        {
            "type": error["type"],
            "location": list(error["loc"]),
            "message": error["msg"],
        }
        for error in exc.errors()
    ]

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "details": {
                    "errors": errors,
                },
            }
        },
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "ROUTE_NOT_FOUND",
                    "message": "The requested API route was not found.",
                    "details": {
                        "path": request.url.path,
                    },
                }
            },
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": str(exc.detail),
                "details": {},
            }
        },
        headers=exc.headers,
    )


async def unexpected_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        exc_info=exc,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected internal error occurred.",
                "details": {
                    "path": request.url.path,
                },
            }
        },
    )


def register_exception_handlers(
    app: FastAPI,
) -> None:
    app.add_exception_handler(
        AppError,
        app_error_handler,
    )

    app.add_exception_handler(
        RequestValidationError,
        request_validation_error_handler,
    )

    app.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,
    )

    app.add_exception_handler(
        Exception,
        unexpected_exception_handler,
    )
