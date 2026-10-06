from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.errors import register_exception_handlers


class ExampleRequest(BaseModel):
    name: str = Field(
        min_length=1,
    )
    password: str = Field(
        min_length=15,
    )


app = FastAPI()

register_exception_handlers(app)


@app.post("/example")
async def example_endpoint(
    data: ExampleRequest,
) -> dict[str, str]:
    return {
        "name": data.name,
    }


client = TestClient(app)


def test_validation_error_uses_standard_error_contract() -> None:
    response = client.post(
        "/example",
        json={
            "name": "",
            "password": "this-is-a-valid-password",
        },
    )

    assert response.status_code == (
        status.HTTP_422_UNPROCESSABLE_CONTENT
    )

    body = response.json()

    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == (
        "Request validation failed."
    )

    errors = body["error"]["details"]["errors"]

    assert len(errors) == 1

    validation_error = errors[0]

    assert set(validation_error) == {
        "type",
        "location",
        "message",
    }
    assert validation_error["location"] == [
        "body",
        "name",
    ]


def test_validation_error_does_not_expose_input_values() -> None:
    secret_input = "short-secret"

    response = client.post(
        "/example",
        json={
            "name": "Example",
            "password": secret_input,
        },
    )

    assert response.status_code == (
        status.HTTP_422_UNPROCESSABLE_CONTENT
    )

    assert secret_input not in response.text

    body = response.json()

    assert body["error"]["code"] == "VALIDATION_ERROR"

    errors = body["error"]["details"]["errors"]

    assert all(
        "input" not in error
        for error in errors
    )


def test_malformed_json_uses_standard_error_contract() -> None:
    response = client.post(
        "/example",
        content="{broken-json",
        headers={
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == (
        status.HTTP_422_UNPROCESSABLE_CONTENT
    )

    body = response.json()

    assert body["error"]["code"] == "VALIDATION_ERROR"

    errors = body["error"]["details"]["errors"]

    assert len(errors) == 1
    assert errors[0]["type"] == "json_invalid"

    assert set(errors[0]) == {
        "type",
        "location",
        "message",
    }
