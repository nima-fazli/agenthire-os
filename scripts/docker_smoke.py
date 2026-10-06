import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from scripts.smoke_cleanup import cleanup_smoke_data

API_BASE_URL = os.getenv(
    "AGENTHIRE_API_BASE_URL",
    "http://api:8000",
).rstrip("/")
REQUEST_TIMEOUT_SECONDS = 10
SMOKE_PASSWORD = "AgentHire-Smoke-Password-2026!"


class SmokeFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class ApiResponse:
    status_code: int
    body: Any
    text: str


def request_json(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> ApiResponse:
    body_bytes = None
    headers = {
        "Accept": "application/json",
    }

    if payload is not None:
        body_bytes = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(
        url=f"{API_BASE_URL}{path}",
        data=body_bytes,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            status_code = response.status
            response_text = response.read().decode("utf-8")
    except HTTPError as exc:
        status_code = exc.code
        response_text = exc.read().decode("utf-8")
    except URLError as exc:
        raise SmokeFailure(
            f"Could not reach API at {API_BASE_URL}: {exc.reason}"
        ) from exc

    response_body: Any = None

    if response_text:
        try:
            response_body = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise SmokeFailure(
                f"Non-JSON response from {method} {path}: "
                f"{response_text!r}"
            ) from exc

    return ApiResponse(
        status_code=status_code,
        body=response_body,
        text=response_text,
    )


def expect_status(
    response: ApiResponse,
    expected_status: int,
    *,
    step: str,
) -> None:
    if response.status_code != expected_status:
        raise SmokeFailure(
            f"{step}: expected HTTP {expected_status}, "
            f"got {response.status_code}: {response.text}"
        )


def expect_error_code(
    response: ApiResponse,
    expected_code: str,
    *,
    step: str,
) -> None:
    try:
        actual_code = response.body["error"]["code"]
    except (KeyError, TypeError) as exc:
        raise SmokeFailure(
            f"{step}: response did not contain "
            "the standard error contract"
        ) from exc

    if actual_code != expected_code:
        raise SmokeFailure(
            f"{step}: expected error code "
            f"{expected_code!r}, got {actual_code!r}"
        )


def log_ok(message: str) -> None:
    print(
        f"[ok] {message}",
        flush=True,
    )


def run_http_smoke(
    *,
    owner_email: str,
    outsider_email: str,
    organization_slug: str,
) -> None:
    health = request_json(
        "GET",
        "/health",
    )

    expect_status(
        health,
        200,
        step="health check",
    )

    if health.body.get("status") != "ok":
        raise SmokeFailure(
            "health check: API did not report status=ok"
        )

    log_ok(
        "health endpoint"
    )

    missing_token = request_json(
        "GET",
        "/users/me",
    )

    expect_status(
        missing_token,
        401,
        step="missing bearer token",
    )

    expect_error_code(
        missing_token,
        "INVALID_ACCESS_TOKEN",
        step="missing bearer token",
    )

    log_ok(
        "protected endpoint rejects missing bearer token"
    )

    owner_registration = request_json(
        "POST",
        "/users/register",
        payload={
            "email": owner_email,
            "password": SMOKE_PASSWORD,
        },
    )

    expect_status(
        owner_registration,
        201,
        step="owner registration",
    )

    if (
        owner_registration.body.get("email")
        != owner_email
    ):
        raise SmokeFailure(
            "owner registration: "
            "unexpected email in response"
        )

    log_ok(
        "owner registration"
    )

    owner_login = request_json(
        "POST",
        "/auth/login",
        payload={
            "email": owner_email,
            "password": SMOKE_PASSWORD,
        },
    )

    expect_status(
        owner_login,
        200,
        step="owner login",
    )

    owner_token = owner_login.body.get(
        "access_token"
    )

    if (
        not isinstance(owner_token, str)
        or not owner_token
    ):
        raise SmokeFailure(
            "owner login: access token was missing"
        )

    log_ok(
        "owner login"
    )

    current_user = request_json(
        "GET",
        "/users/me",
        token=owner_token,
    )

    expect_status(
        current_user,
        200,
        step="current user",
    )

    if (
        current_user.body.get("email")
        != owner_email
    ):
        raise SmokeFailure(
            "current user: token resolved "
            "to the wrong user"
        )

    log_ok(
        "bearer token resolves current user"
    )

    organization = request_json(
        "POST",
        "/organizations",
        token=owner_token,
        payload={
            "name": "AgentHire Smoke Organization",
            "slug": organization_slug,
        },
    )

    expect_status(
        organization,
        201,
        step="organization creation",
    )

    organization_id = organization.body.get(
        "id"
    )

    if not isinstance(
        organization_id,
        str,
    ):
        raise SmokeFailure(
            "organization creation: id was missing"
        )

    log_ok(
        "organization creation with owner membership"
    )

    organizations = request_json(
        "GET",
        "/organizations",
        token=owner_token,
    )

    expect_status(
        organizations,
        200,
        step="organization listing",
    )

    if not any(
        item.get("id") == organization_id
        for item in organizations.body
    ):
        raise SmokeFailure(
            "organization listing: "
            "created organization was missing"
        )

    log_ok(
        "organization listing is membership scoped"
    )

    job = request_json(
        "POST",
        f"/organizations/{organization_id}/jobs",
        token=owner_token,
        payload={
            "title": "AI Backend Engineer",
            "description": "Docker smoke-test job.",
            "status": "draft",
        },
    )

    expect_status(
        job,
        201,
        step="job creation",
    )

    job_id = job.body.get(
        "id"
    )

    if not isinstance(
        job_id,
        str,
    ):
        raise SmokeFailure(
            "job creation: id was missing"
        )

    log_ok(
        "tenant-scoped job creation"
    )

    retrieved_job = request_json(
        "GET",
        (
            f"/organizations/"
            f"{organization_id}/jobs/{job_id}"
        ),
        token=owner_token,
    )

    expect_status(
        retrieved_job,
        200,
        step="job retrieval",
    )

    if (
        retrieved_job.body.get(
            "organization_id"
        )
        != organization_id
    ):
        raise SmokeFailure(
            "job retrieval: wrong organization_id"
        )

    log_ok(
        "tenant-scoped job retrieval"
    )

    updated_job = request_json(
        "PATCH",
        (
            f"/organizations/"
            f"{organization_id}/jobs/{job_id}"
        ),
        token=owner_token,
        payload={
            "title": "Senior AI Backend Engineer",
            "status": "open",
        },
    )

    expect_status(
        updated_job,
        200,
        step="job update",
    )

    if (
        updated_job.body.get("status")
        != "open"
    ):
        raise SmokeFailure(
            "job update: status was not persisted"
        )

    log_ok(
        "tenant-scoped job update"
    )

    jobs = request_json(
        "GET",
        f"/organizations/{organization_id}/jobs",
        token=owner_token,
    )

    expect_status(
        jobs,
        200,
        step="job listing",
    )

    if not any(
        item.get("id") == job_id
        for item in jobs.body
    ):
        raise SmokeFailure(
            "job listing: created job was missing"
        )

    log_ok(
        "tenant-scoped job listing"
    )

    outsider_registration = request_json(
        "POST",
        "/users/register",
        payload={
            "email": outsider_email,
            "password": SMOKE_PASSWORD,
        },
    )

    expect_status(
        outsider_registration,
        201,
        step="outsider registration",
    )

    log_ok(
        "outsider registration"
    )

    outsider_login = request_json(
        "POST",
        "/auth/login",
        payload={
            "email": outsider_email,
            "password": SMOKE_PASSWORD,
        },
    )

    expect_status(
        outsider_login,
        200,
        step="outsider login",
    )

    outsider_token = outsider_login.body.get(
        "access_token"
    )

    if (
        not isinstance(outsider_token, str)
        or not outsider_token
    ):
        raise SmokeFailure(
            "outsider login: access token was missing"
        )

    log_ok(
        "outsider login"
    )

    hidden_organization = request_json(
        "GET",
        f"/organizations/{organization_id}",
        token=outsider_token,
    )

    expect_status(
        hidden_organization,
        404,
        step="organization tenant isolation",
    )

    expect_error_code(
        hidden_organization,
        "ORGANIZATION_NOT_FOUND",
        step="organization tenant isolation",
    )

    log_ok(
        "organization is hidden from non-member"
    )

    hidden_jobs = request_json(
        "GET",
        f"/organizations/{organization_id}/jobs",
        token=outsider_token,
    )

    expect_status(
        hidden_jobs,
        404,
        step="job tenant isolation",
    )

    expect_error_code(
        hidden_jobs,
        "ORGANIZATION_NOT_FOUND",
        step="job tenant isolation",
    )

    log_ok(
        "jobs are hidden from non-member"
    )


async def main() -> None:
    run_id = uuid4().hex[:12]

    owner_email = (
        f"smoke-owner-{run_id}@example.com"
    )
    outsider_email = (
        f"smoke-outsider-{run_id}@example.com"
    )
    organization_slug = (
        f"smoke-{run_id}"
    )

    try:
        run_http_smoke(
            owner_email=owner_email,
            outsider_email=outsider_email,
            organization_slug=organization_slug,
        )
    finally:
        await cleanup_smoke_data(
            organization_slug=organization_slug,
            user_emails=(
                owner_email,
                outsider_email,
            ),
        )

        log_ok(
            "smoke data cleanup"
        )

    print(
        "[success] Docker real-stack "
        "smoke flow passed.",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(
        main()
    )
