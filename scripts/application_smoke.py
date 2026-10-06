import asyncio
import os
from uuid import uuid4

import asyncpg

from scripts.candidate_smoke import (
    cleanup_candidate_rows,
)
from scripts.docker_smoke import (
    SMOKE_PASSWORD,
    SmokeFailure,
    expect_error_code,
    expect_status,
    log_ok,
    request_json,
)
from scripts.smoke_cleanup import cleanup_smoke_data


async def cleanup_application_rows(
    organization_slug: str,
) -> None:
    connection = await asyncpg.connect(
        host=os.environ["AGENTHIRE_POSTGRES_HOST"],
        port=int(
            os.environ[
                "AGENTHIRE_POSTGRES_PORT"
            ]
        ),
        database=os.environ[
            "AGENTHIRE_POSTGRES_DB"
        ],
        user=os.environ[
            "AGENTHIRE_POSTGRES_USER"
        ],
        password=os.environ[
            "AGENTHIRE_POSTGRES_PASSWORD"
        ],
    )

    try:
        await connection.execute(
            """
            DELETE FROM applications
            WHERE organization_id = (
                SELECT id
                FROM organizations
                WHERE slug = $1
            )
            """,
            organization_slug,
        )
    finally:
        await connection.close()


def run_application_smoke(
    *,
    owner_email: str,
    outsider_email: str,
    organization_slug: str,
) -> None:
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
        step="application smoke owner registration",
    )

    log_ok(
        "application smoke owner registration"
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
        step="application smoke owner login",
    )

    owner_token = owner_login.body.get(
        "access_token"
    )

    if (
        not isinstance(owner_token, str)
        or not owner_token
    ):
        raise SmokeFailure(
            "application smoke owner login: "
            "access token was missing"
        )

    log_ok(
        "application smoke owner login"
    )

    organization = request_json(
        "POST",
        "/organizations",
        token=owner_token,
        payload={
            "name": "Application Smoke Organization",
            "slug": organization_slug,
        },
    )

    expect_status(
        organization,
        201,
        step="application smoke organization creation",
    )

    organization_id = organization.body.get(
        "id"
    )

    if not isinstance(
        organization_id,
        str,
    ):
        raise SmokeFailure(
            "application smoke organization creation: "
            "organization id was missing"
        )

    log_ok(
        "application smoke organization creation"
    )

    job = request_json(
        "POST",
        f"/organizations/{organization_id}/jobs",
        token=owner_token,
        payload={
            "title": "AI Platform Engineer",
            "description": (
                "Build production AI systems."
            ),
            "status": "open",
        },
    )

    expect_status(
        job,
        201,
        step="application smoke job creation",
    )

    job_id = job.body.get(
        "id"
    )

    if not isinstance(
        job_id,
        str,
    ):
        raise SmokeFailure(
            "application smoke job creation: "
            "job id was missing"
        )

    log_ok(
        "application smoke job creation"
    )

    candidate = request_json(
        "POST",
        f"/organizations/{organization_id}/candidates",
        token=owner_token,
        payload={
            "full_name": "Ada Lovelace",
            "email": "ada@example.com",
            "location": "Amsterdam",
            "headline": "AI Engineer",
        },
    )

    expect_status(
        candidate,
        201,
        step="application smoke candidate creation",
    )

    candidate_id = candidate.body.get(
        "id"
    )

    if not isinstance(
        candidate_id,
        str,
    ):
        raise SmokeFailure(
            "application smoke candidate creation: "
            "candidate id was missing"
        )

    log_ok(
        "application smoke candidate creation"
    )

    application = request_json(
        "POST",
        (
            f"/organizations/"
            f"{organization_id}/applications"
        ),
        token=owner_token,
        payload={
            "job_id": job_id,
            "candidate_id": candidate_id,
        },
    )

    expect_status(
        application,
        201,
        step="application creation",
    )

    application_id = application.body.get(
        "id"
    )

    if not isinstance(
        application_id,
        str,
    ):
        raise SmokeFailure(
            "application creation: "
            "application id was missing"
        )

    if (
        application.body.get("job_id")
        != job_id
    ):
        raise SmokeFailure(
            "application creation: "
            "wrong job_id"
        )

    if (
        application.body.get(
            "candidate_id"
        )
        != candidate_id
    ):
        raise SmokeFailure(
            "application creation: "
            "wrong candidate_id"
        )

    log_ok(
        "tenant-scoped application creation"
    )

    duplicate = request_json(
        "POST",
        (
            f"/organizations/"
            f"{organization_id}/applications"
        ),
        token=owner_token,
        payload={
            "job_id": job_id,
            "candidate_id": candidate_id,
        },
    )

    expect_status(
        duplicate,
        409,
        step="duplicate application rejection",
    )

    expect_error_code(
        duplicate,
        "APPLICATION_ALREADY_EXISTS",
        step="duplicate application rejection",
    )

    log_ok(
        "duplicate application is rejected"
    )

    applications = request_json(
        "GET",
        (
            f"/organizations/"
            f"{organization_id}/applications"
        ),
        token=owner_token,
    )

    expect_status(
        applications,
        200,
        step="application listing",
    )

    if not any(
        item.get("id") == application_id
        for item in applications.body
    ):
        raise SmokeFailure(
            "application listing: "
            "created application was missing"
        )

    log_ok(
        "tenant-scoped application listing"
    )

    retrieved_application = request_json(
        "GET",
        (
            f"/organizations/"
            f"{organization_id}/applications/"
            f"{application_id}"
        ),
        token=owner_token,
    )

    expect_status(
        retrieved_application,
        200,
        step="application retrieval",
    )

    if (
        retrieved_application.body.get(
            "organization_id"
        )
        != organization_id
    ):
        raise SmokeFailure(
            "application retrieval: "
            "wrong organization_id"
        )

    log_ok(
        "tenant-scoped application retrieval"
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
        step="application smoke outsider registration",
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
        step="application smoke outsider login",
    )

    outsider_token = outsider_login.body.get(
        "access_token"
    )

    if (
        not isinstance(outsider_token, str)
        or not outsider_token
    ):
        raise SmokeFailure(
            "application smoke outsider login: "
            "access token was missing"
        )

    log_ok(
        "application smoke outsider login"
    )

    hidden_applications = request_json(
        "GET",
        (
            f"/organizations/"
            f"{organization_id}/applications"
        ),
        token=outsider_token,
    )

    expect_status(
        hidden_applications,
        404,
        step="application list tenant isolation",
    )

    expect_error_code(
        hidden_applications,
        "ORGANIZATION_NOT_FOUND",
        step="application list tenant isolation",
    )

    log_ok(
        "application list is hidden from non-member"
    )

    hidden_application = request_json(
        "GET",
        (
            f"/organizations/"
            f"{organization_id}/applications/"
            f"{application_id}"
        ),
        token=outsider_token,
    )

    expect_status(
        hidden_application,
        404,
        step="application retrieval tenant isolation",
    )

    expect_error_code(
        hidden_application,
        "ORGANIZATION_NOT_FOUND",
        step="application retrieval tenant isolation",
    )

    log_ok(
        "application is hidden from non-member"
    )

    hidden_create = request_json(
        "POST",
        (
            f"/organizations/"
            f"{organization_id}/applications"
        ),
        token=outsider_token,
        payload={
            "job_id": job_id,
            "candidate_id": candidate_id,
        },
    )

    expect_status(
        hidden_create,
        404,
        step="application creation tenant isolation",
    )

    expect_error_code(
        hidden_create,
        "ORGANIZATION_NOT_FOUND",
        step="application creation tenant isolation",
    )

    log_ok(
        "application creation is hidden from non-member"
    )


async def main() -> None:
    run_id = uuid4().hex[:12]

    owner_email = (
        f"application-owner-{run_id}@example.com"
    )
    outsider_email = (
        f"application-outsider-{run_id}@example.com"
    )
    organization_slug = (
        f"application-smoke-{run_id}"
    )

    try:
        run_application_smoke(
            owner_email=owner_email,
            outsider_email=outsider_email,
            organization_slug=organization_slug,
        )
    finally:
        try:
            await cleanup_application_rows(
                organization_slug
            )
        finally:
            try:
                await cleanup_candidate_rows(
                    organization_slug
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
            "application smoke data cleanup"
        )

    print(
        "[success] Application Docker "
        "real-stack smoke flow passed.",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(
        main()
    )
