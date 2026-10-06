import asyncio
import os
from uuid import uuid4

import asyncpg

from scripts.docker_smoke import (
    SMOKE_PASSWORD,
    SmokeFailure,
    expect_error_code,
    expect_status,
    log_ok,
    request_json,
)
from scripts.smoke_cleanup import cleanup_smoke_data


async def cleanup_candidate_rows(
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
            DELETE FROM candidates
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


def run_candidate_smoke(
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
        step="candidate smoke owner registration",
    )

    log_ok(
        "candidate smoke owner registration"
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
        step="candidate smoke owner login",
    )

    owner_token = owner_login.body.get(
        "access_token"
    )

    if (
        not isinstance(owner_token, str)
        or not owner_token
    ):
        raise SmokeFailure(
            "candidate smoke owner login: "
            "access token was missing"
        )

    log_ok(
        "candidate smoke owner login"
    )

    organization = request_json(
        "POST",
        "/organizations",
        token=owner_token,
        payload={
            "name": "Candidate Smoke Organization",
            "slug": organization_slug,
        },
    )

    expect_status(
        organization,
        201,
        step="candidate smoke organization creation",
    )

    organization_id = organization.body.get(
        "id"
    )

    if not isinstance(
        organization_id,
        str,
    ):
        raise SmokeFailure(
            "candidate smoke organization creation: "
            "organization id was missing"
        )

    log_ok(
        "candidate smoke organization creation"
    )

    candidate = request_json(
        "POST",
        f"/organizations/{organization_id}/candidates",
        token=owner_token,
        payload={
            "full_name": " Ada Lovelace ",
            "email": " ADA@EXAMPLE.COM ",
            "phone": "+31 20 123 4567",
            "location": " Amsterdam ",
            "headline": " AI Engineer ",
            "summary": (
                " Builds intelligent systems. "
            ),
        },
    )

    expect_status(
        candidate,
        201,
        step="candidate creation",
    )

    candidate_id = candidate.body.get(
        "id"
    )

    if not isinstance(
        candidate_id,
        str,
    ):
        raise SmokeFailure(
            "candidate creation: "
            "candidate id was missing"
        )

    if (
        candidate.body.get("email")
        != "ada@example.com"
    ):
        raise SmokeFailure(
            "candidate creation: "
            "email normalization was not persisted"
        )

    log_ok(
        "tenant-scoped candidate creation"
    )

    candidates = request_json(
        "GET",
        f"/organizations/{organization_id}/candidates",
        token=owner_token,
    )

    expect_status(
        candidates,
        200,
        step="candidate listing",
    )

    if not any(
        item.get("id") == candidate_id
        for item in candidates.body
    ):
        raise SmokeFailure(
            "candidate listing: "
            "created candidate was missing"
        )

    log_ok(
        "tenant-scoped candidate listing"
    )

    retrieved_candidate = request_json(
        "GET",
        (
            f"/organizations/"
            f"{organization_id}/candidates/"
            f"{candidate_id}"
        ),
        token=owner_token,
    )

    expect_status(
        retrieved_candidate,
        200,
        step="candidate retrieval",
    )

    if (
        retrieved_candidate.body.get(
            "organization_id"
        )
        != organization_id
    ):
        raise SmokeFailure(
            "candidate retrieval: "
            "wrong organization_id"
        )

    log_ok(
        "tenant-scoped candidate retrieval"
    )

    updated_candidate = request_json(
        "PATCH",
        (
            f"/organizations/"
            f"{organization_id}/candidates/"
            f"{candidate_id}"
        ),
        token=owner_token,
        payload={
            "full_name": " Ada Byron ",
            "email": " ADA.BYRON@EXAMPLE.COM ",
            "headline": " Principal AI Engineer ",
        },
    )

    expect_status(
        updated_candidate,
        200,
        step="candidate update",
    )

    if (
        updated_candidate.body.get(
            "full_name"
        )
        != "Ada Byron"
    ):
        raise SmokeFailure(
            "candidate update: "
            "full_name was not persisted"
        )

    if (
        updated_candidate.body.get("email")
        != "ada.byron@example.com"
    ):
        raise SmokeFailure(
            "candidate update: "
            "email normalization was not persisted"
        )

    if (
        updated_candidate.body.get(
            "headline"
        )
        != "Principal AI Engineer"
    ):
        raise SmokeFailure(
            "candidate update: "
            "headline was not persisted"
        )

    log_ok(
        "tenant-scoped candidate update"
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
        step="candidate smoke outsider registration",
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
        step="candidate smoke outsider login",
    )

    outsider_token = outsider_login.body.get(
        "access_token"
    )

    if (
        not isinstance(outsider_token, str)
        or not outsider_token
    ):
        raise SmokeFailure(
            "candidate smoke outsider login: "
            "access token was missing"
        )

    log_ok(
        "candidate smoke outsider login"
    )

    hidden_candidates = request_json(
        "GET",
        f"/organizations/{organization_id}/candidates",
        token=outsider_token,
    )

    expect_status(
        hidden_candidates,
        404,
        step="candidate list tenant isolation",
    )

    expect_error_code(
        hidden_candidates,
        "ORGANIZATION_NOT_FOUND",
        step="candidate list tenant isolation",
    )

    log_ok(
        "candidate list is hidden from non-member"
    )

    hidden_candidate = request_json(
        "GET",
        (
            f"/organizations/"
            f"{organization_id}/candidates/"
            f"{candidate_id}"
        ),
        token=outsider_token,
    )

    expect_status(
        hidden_candidate,
        404,
        step="candidate retrieval tenant isolation",
    )

    expect_error_code(
        hidden_candidate,
        "ORGANIZATION_NOT_FOUND",
        step="candidate retrieval tenant isolation",
    )

    log_ok(
        "candidate is hidden from non-member"
    )

    hidden_update = request_json(
        "PATCH",
        (
            f"/organizations/"
            f"{organization_id}/candidates/"
            f"{candidate_id}"
        ),
        token=outsider_token,
        payload={
            "headline": "Unauthorized Update",
        },
    )

    expect_status(
        hidden_update,
        404,
        step="candidate update tenant isolation",
    )

    expect_error_code(
        hidden_update,
        "ORGANIZATION_NOT_FOUND",
        step="candidate update tenant isolation",
    )

    log_ok(
        "candidate update is hidden from non-member"
    )


async def main() -> None:
    run_id = uuid4().hex[:12]

    owner_email = (
        f"candidate-owner-{run_id}@example.com"
    )
    outsider_email = (
        f"candidate-outsider-{run_id}@example.com"
    )
    organization_slug = (
        f"candidate-smoke-{run_id}"
    )

    try:
        run_candidate_smoke(
            owner_email=owner_email,
            outsider_email=outsider_email,
            organization_slug=organization_slug,
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
            "candidate smoke data cleanup"
        )

    print(
        "[success] Candidate Docker "
        "real-stack smoke flow passed.",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(
        main()
    )
