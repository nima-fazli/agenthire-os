from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import AppError, register_exception_handlers


def create_test_app() -> FastAPI:
    app = FastAPI()

    register_exception_handlers(app)

    @app.get("/raise-app-error")
    async def raise_app_error() -> None:
        raise AppError(
            code="TEST_ERROR",
            message="A test application error occurred.",
            status_code=400,
            details={
                "field": "example",
            },
        )

    return app


client = TestClient(create_test_app())


def test_app_error_returns_structured_response() -> None:
    response = client.get("/raise-app-error")

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "TEST_ERROR",
            "message": "A test application error occurred.",
            "details": {
                "field": "example",
            },
        }
    }


def test_unknown_route_returns_structured_not_found_error() -> None:
    response = client.get("/route-that-does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "ROUTE_NOT_FOUND",
            "message": "The requested API route was not found.",
            "details": {
                "path": "/route-that-does-not-exist",
            },
        }
    }
