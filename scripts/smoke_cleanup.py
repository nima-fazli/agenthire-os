import os
from collections.abc import Sequence

import asyncpg


async def cleanup_smoke_data(
    *,
    organization_slug: str,
    user_emails: Sequence[str],
) -> None:
    connection = await asyncpg.connect(
        host=os.environ["AGENTHIRE_POSTGRES_HOST"],
        port=int(os.environ["AGENTHIRE_POSTGRES_PORT"]),
        database=os.environ["AGENTHIRE_POSTGRES_DB"],
        user=os.environ["AGENTHIRE_POSTGRES_USER"],
        password=os.environ["AGENTHIRE_POSTGRES_PASSWORD"],
    )

    try:
        async with connection.transaction():
            organization_id = await connection.fetchval(
                "SELECT id FROM organizations WHERE slug = $1",
                organization_slug,
            )

            user_rows = await connection.fetch(
                "SELECT id FROM users WHERE email = ANY($1::text[])",
                list(user_emails),
            )
            user_ids = [row["id"] for row in user_rows]

            if organization_id is not None:
                await connection.execute(
                    "DELETE FROM jobs WHERE organization_id = $1",
                    organization_id,
                )
                await connection.execute(
                    "DELETE FROM organization_memberships "
                    "WHERE organization_id = $1",
                    organization_id,
                )
                await connection.execute(
                    "DELETE FROM organizations WHERE id = $1",
                    organization_id,
                )

            for user_id in user_ids:
                await connection.execute(
                    "DELETE FROM organization_memberships WHERE user_id = $1",
                    user_id,
                )

            for user_id in user_ids:
                await connection.execute(
                    "DELETE FROM users WHERE id = $1",
                    user_id,
                )
    finally:
        await connection.close()
