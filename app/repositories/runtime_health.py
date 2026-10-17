from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

QUEUE_SQL = """
SELECT 'extraction' AS queue,
       count(*) FILTER (WHERE status = 'queued') AS queued,
       count(*) FILTER (WHERE status = 'running') AS running,
       count(*) FILTER (
           WHERE status = 'running' AND lease_expires_at <= statement_timestamp()
       ) AS expired_leases,
       coalesce(greatest(0, extract(epoch FROM (
           statement_timestamp() - min(created_at) FILTER (WHERE status = 'queued')
       )))::bigint, 0) AS oldest_queued_seconds
FROM document_extractions
UNION ALL
SELECT 'embedding',
       count(*) FILTER (WHERE status = 'queued'),
       count(*) FILTER (WHERE status = 'running'),
       count(*) FILTER (
           WHERE status = 'running' AND lease_expires_at <= statement_timestamp()
       ),
       coalesce(greatest(0, extract(epoch FROM (
           statement_timestamp() - min(created_at) FILTER (WHERE status = 'queued')
       )))::bigint, 0)
FROM document_embedding_jobs
"""


class RuntimeHealthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def configure(self) -> None:
        await self._session.execute(text("SET TRANSACTION READ ONLY"))
        await self._session.execute(text("SET LOCAL statement_timeout = '1000ms'"))
        await self._session.execute(text("SET LOCAL lock_timeout = '500ms'"))

    async def migration_heads(self) -> frozenset[str]:
        result = await self._session.execute(
            text("SELECT version_num FROM alembic_version")
        )
        return frozenset(result.scalars().all())

    async def queues(self) -> dict[str, dict[str, int]]:
        # Local operator access only. No tenant IDs, source text or failure detail.
        result = await self._session.execute(text(QUEUE_SQL))
        return {
            row["queue"]: {
                key: int(row[key])
                for key in ("queued", "running", "expired_leases", "oldest_queued_seconds")
            }
            for row in result.mappings().all()
        }
