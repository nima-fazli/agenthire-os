import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import asyncpg

from scripts.candidate_smoke import cleanup_candidate_rows
from scripts.docker_smoke import (
    SMOKE_PASSWORD,
    ApiResponse,
    SmokeFailure,
    expect_error_code,
    expect_status,
    log_ok,
    request_json,
)
from scripts.smoke_cleanup import cleanup_smoke_data


async def cleanup_application_rows(organization_slug: str) -> None:
    connection = await asyncpg.connect(
        host=os.environ["AGENTHIRE_POSTGRES_HOST"],
        port=int(os.environ["AGENTHIRE_POSTGRES_PORT"]),
        database=os.environ["AGENTHIRE_POSTGRES_DB"],
        user=os.environ["AGENTHIRE_POSTGRES_USER"],
        password=os.environ["AGENTHIRE_POSTGRES_PASSWORD"],
    )
    try:
        await connection.execute(
            """
            DELETE FROM applications
            WHERE organization_id = (
                SELECT id FROM organizations WHERE slug = $1
            )
            """,
            organization_slug,
        )
    finally:
        await connection.close()


def checked_request(
    method: str,
    path: str,
    *,
    step: str,
    expected: int = 200,
    token: str | None = None,
    payload: dict | None = None,
    error_code: str | None = None,
) -> ApiResponse:
    response = request_json(method, path, token=token, payload=payload)

    expect_status(response, expected, step=step)

    if error_code is not None:
        expect_error_code(response, error_code, step=step)

    log_ok(step)
    return response


def response_id(response: ApiResponse, *, step: str) -> str:
    value = response.body.get("id")

    if not isinstance(value, str) or not value:
        raise SmokeFailure(f"{step}: resource id was missing")

    return value


def expect_application_status(
    response: ApiResponse, expected: str, *, step: str
) -> None:
    if response.body.get("status") != expected:
        raise SmokeFailure(f"{step}: expected application status {expected!r}")


def register_and_login(email: str, *, label: str) -> str:
    payload = {"email": email, "password": SMOKE_PASSWORD}

    checked_request(
        "POST",
        "/users/register",
        payload=payload,
        expected=201,
        step=f"{label} registration",
    )

    login = checked_request(
        "POST", "/auth/login", payload=payload, step=f"{label} login"
    )

    token = login.body.get("access_token")

    if not isinstance(token, str) or not token:
        raise SmokeFailure(f"{label}: access token was missing")

    return token


def create_workflow_application(
    *,
    organization_id: str,
    job_id: str,
    token: str,
    label: str,
) -> str:
    candidate = checked_request(
        "POST",
        f"/organizations/{organization_id}/candidates",
        token=token,
        payload={"full_name": f"Workflow Smoke {label}"},
        expected=201,
        step=f"{label} candidate creation",
    )

    candidate_id = response_id(candidate, step=label)

    application = checked_request(
        "POST",
        f"/organizations/{organization_id}/applications",
        token=token,
        payload={"job_id": job_id, "candidate_id": candidate_id},
        expected=201,
        step=f"{label} application creation",
    )

    expect_application_status(application, "applied", step=label)

    if (
        application.body.get("job_id") != job_id
        or application.body.get("candidate_id") != candidate_id
        or application.body.get("organization_id") != organization_id
    ):
        raise SmokeFailure(f"{label}: application resource references were incorrect")

    return response_id(application, step=label)


def verify_application_workflow(
    *,
    organization_id: str,
    job_id: str,
    application_id: str,
    owner_token: str,
    outsider_token: str,
) -> None:
    path = f"/organizations/{organization_id}/applications/{application_id}"
    transition_path = f"{path}/transitions"
    conflict = "INVALID_APPLICATION_STATUS_TRANSITION"

    for token, expected, code in [
        (None, 401, "INVALID_ACCESS_TOKEN"),
        (outsider_token, 404, "ORGANIZATION_NOT_FOUND"),
    ]:
        checked_request(
            "POST",
            transition_path,
            token=token,
            payload={"status": "screening"},
            expected=expected,
            error_code=code,
            step="transition access control",
        )

    for payload in [
        {"status": "unknown"},
        {"status": "screening", "extra": True},
    ]:
        checked_request(
            "POST",
            transition_path,
            token=owner_token,
            payload=payload,
            expected=422,
            error_code="VALIDATION_ERROR",
            step="transition body validation",
        )

    checked_request(
        "POST",
        f"/organizations/{organization_id}/applications/{uuid4()}/transitions",
        token=owner_token,
        payload={"status": "screening"},
        expected=404,
        error_code="APPLICATION_NOT_FOUND",
        step="missing application transition",
    )

    checked_request(
        "POST",
        transition_path,
        token=owner_token,
        payload={"status": "hired"},
        expected=409,
        error_code=conflict,
        step="skipped application stage",
    )

    unchanged = checked_request(
        "GET",
        path,
        token=owner_token,
        step="status after invalid transition",
    )

    expect_application_status(
        unchanged, "applied", step="invalid transition rollback"
    )

    for status in ["applied", "screening", "interview", "offer", "hired"]:
        transitioned = checked_request(
            "POST",
            transition_path,
            token=owner_token,
            payload={"status": status},
            step=f"transition to {status}",
        )

        expect_application_status(
            transitioned, status, step="forward transition"
        )

        retry = checked_request(
            "POST",
            transition_path,
            token=owner_token,
            payload={"status": status},
            step=f"same-state retry for {status}",
        )

        expect_application_status(retry, status, step="same-state retry")

        if retry.body["updated_at"] != transitioned.body["updated_at"]:
            raise SmokeFailure("Same-state retry changed updated_at")

    checked_request(
        "POST",
        transition_path,
        token=owner_token,
        payload={"status": "rejected"},
        expected=409,
        error_code=conflict,
        step="hired terminal state",
    )

    final = checked_request(
        "GET", path, token=owner_token, step="persisted hired status"
    )

    expect_application_status(final, "hired", step="persisted hired status")

    active_stages = ["applied", "screening", "interview", "offer"]

    for index, stage in enumerate(active_stages):
        reject_id = create_workflow_application(
            organization_id=organization_id,
            job_id=job_id,
            token=owner_token,
            label=f"reject-{stage}",
        )

        reject_path = (
            f"/organizations/{organization_id}"
            f"/applications/{reject_id}/transitions"
        )

        for forward_stage in active_stages[1:index + 1]:
            forward = checked_request(
                "POST",
                reject_path,
                token=owner_token,
                payload={"status": forward_stage},
                step=f"prepare rejection from {stage}",
            )

            expect_application_status(
                forward, forward_stage, step="prepare rejection"
            )

        rejected = checked_request(
            "POST",
            reject_path,
            token=owner_token,
            payload={"status": "rejected"},
            step=f"rejection from {stage}",
        )

        expect_application_status(rejected, "rejected", step="rejection")

        retry = checked_request(
            "POST",
            reject_path,
            token=owner_token,
            payload={"status": "rejected"},
            step="rejected same-state retry",
        )

        expect_application_status(
            retry, "rejected", step="rejected same-state retry"
        )

        if retry.body["updated_at"] != rejected.body["updated_at"]:
            raise SmokeFailure("Rejected same-state retry changed updated_at")

        checked_request(
            "POST",
            reject_path,
            token=owner_token,
            payload={"status": "screening"},
            expected=409,
            error_code=conflict,
            step="rejected terminal state",
        )

    concurrent_id = create_workflow_application(
        organization_id=organization_id,
        job_id=job_id,
        token=owner_token,
        label="concurrent",
    )

    concurrent_path = (
        f"/organizations/{organization_id}/applications/{concurrent_id}"
    )

    start = Barrier(2, timeout=10)

    def send_transition(status: str) -> ApiResponse:
        start.wait()

        return request_json(
            "POST",
            f"{concurrent_path}/transitions",
            token=owner_token,
            payload={"status": status},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        screening_future = executor.submit(send_transition, "screening")
        rejected_future = executor.submit(send_transition, "rejected")

        screening = screening_future.result(timeout=20)
        rejected = rejected_future.result(timeout=20)

    expect_status(rejected, 200, step="concurrent rejection")
    expect_application_status(
        rejected, "rejected", step="concurrent rejection"
    )

    if screening.status_code == 200:
        expect_application_status(
            screening, "screening", step="concurrent screening"
        )
    else:
        expect_status(
            screening, 409, step="screening after concurrent rejection"
        )
        expect_error_code(
            screening, conflict, step="concurrent screening"
        )

    final = checked_request(
        "GET",
        concurrent_path,
        token=owner_token,
        step="concurrent persisted status",
    )

    expect_application_status(
        final, "rejected", step="concurrent persisted status"
    )

    log_ok("concurrent screening/rejection preserves terminal rejected status")


def run_application_smoke(
    *,
    owner_email: str,
    outsider_email: str,
    organization_slug: str,
) -> None:
    owner_token = register_and_login(
        owner_email, label="application owner"
    )

    organization = checked_request(
        "POST",
        "/organizations",
        token=owner_token,
        payload={
            "name": "Application Smoke Organization",
            "slug": organization_slug,
        },
        expected=201,
        step="application organization creation",
    )

    organization_id = response_id(
        organization, step="organization creation"
    )

    job = checked_request(
        "POST",
        f"/organizations/{organization_id}/jobs",
        token=owner_token,
        payload={
            "title": "AI Platform Engineer",
            "description": "Build AI systems.",
            "status": "open",
        },
        expected=201,
        step="application job creation",
    )

    job_id = response_id(job, step="job creation")

    application_id = create_workflow_application(
        organization_id=organization_id,
        job_id=job_id,
        token=owner_token,
        label="primary",
    )

    list_path = f"/organizations/{organization_id}/applications"
    application_path = f"{list_path}/{application_id}"

    retrieved = checked_request(
        "GET",
        application_path,
        token=owner_token,
        step="application retrieval",
    )

    expect_application_status(
        retrieved, "applied", step="application retrieval"
    )

    if retrieved.body["organization_id"] != organization_id:
        raise SmokeFailure(
            "Application retrieval returned the wrong organization"
        )

    pair = {
        "job_id": job_id,
        "candidate_id": retrieved.body["candidate_id"],
    }

    checked_request(
        "POST",
        list_path,
        token=owner_token,
        payload=pair,
        expected=409,
        error_code="APPLICATION_ALREADY_EXISTS",
        step="duplicate application rejection",
    )

    listed = checked_request(
        "GET", list_path, token=owner_token, step="application listing"
    )

    if not isinstance(listed.body, list) or not any(
        item.get("id") == application_id
        and item.get("status") == "applied"
        for item in listed.body
    ):
        raise SmokeFailure("Created application was missing from the list")

    outsider_token = register_and_login(
        outsider_email, label="application outsider"
    )

    for method, path, payload in [
        ("GET", list_path, None),
        ("GET", application_path, None),
        ("POST", list_path, pair),
    ]:
        checked_request(
            method,
            path,
            token=outsider_token,
            payload=payload,
            expected=404,
            error_code="ORGANIZATION_NOT_FOUND",
            step="application tenant isolation",
        )

    verify_application_workflow(
        organization_id=organization_id,
        job_id=job_id,
        application_id=application_id,
        owner_token=owner_token,
        outsider_token=outsider_token,
    )


async def main() -> None:
    run_id = uuid4().hex[:12]

    owner_email = f"application-owner-{run_id}@example.com"
    outsider_email = f"application-outsider-{run_id}@example.com"
    organization_slug = f"application-smoke-{run_id}"

    try:
        run_application_smoke(
            owner_email=owner_email,
            outsider_email=outsider_email,
            organization_slug=organization_slug,
        )
    finally:
        try:
            await cleanup_application_rows(organization_slug)
        finally:
            try:
                await cleanup_candidate_rows(organization_slug)
            finally:
                await cleanup_smoke_data(
                    organization_slug=organization_slug,
                    user_emails=(owner_email, outsider_email),
                )

        log_ok("application smoke data cleanup")

    print(
        "[success] Application Docker real-stack smoke flow passed.",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
