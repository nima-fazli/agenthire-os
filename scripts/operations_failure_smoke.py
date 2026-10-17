"""Real read-only DB failure recovery and bounded public health probes."""

import asyncio
import json
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.session import build_database_url
from app.repositories.runtime_health import RuntimeHealthRepository
from scripts.docker_smoke import API_BASE_URL, SmokeFailure, log_ok
from scripts.operations_probe import measure


async def database_checks():
    engine = create_async_engine(build_database_url(get_settings()), poolclass=NullPool, hide_parameters=True)
    try:
        async with asyncio.timeout(10), engine.connect() as connection, AsyncSession(bind=connection) as session:
            async def settings():
                values = []
                for name in ("transaction_read_only", "statement_timeout", "lock_timeout"):
                    values.append((await session.execute(text(f"SHOW {name}"))).scalar_one())
                return tuple(values)

            before = await settings()
            await session.rollback()
            await RuntimeHealthRepository(session).configure()
            await session.execute(text("SET LOCAL statement_timeout = '50ms'"))
            try:
                await session.execute(text("SELECT pg_sleep(0.2)"))
            except DBAPIError as error:
                if getattr(error.orig, "sqlstate", None) != "57014":
                    raise SmokeFailure("Unexpected database failure category") from None
            else:
                raise SmokeFailure("Database statement deadline was not enforced")
            finally:
                await session.rollback()
            if await settings() != before:
                raise SmokeFailure("Transaction-local limits leaked after rollback")
            await session.rollback()
            await RuntimeHealthRepository(session).configure()
            name = "agenthire_readonly_probe_" + uuid4().hex
            try:
                await session.execute(text(f"CREATE TABLE {name} (value integer)"))
            except DBAPIError as error:
                if getattr(error.orig, "sqlstate", None) != "25006":
                    raise SmokeFailure("Unexpected read-only failure category") from None
            else:
                raise SmokeFailure("Read-only diagnostics allowed a schema write")
            finally:
                await session.rollback()
            if await settings() != before or (await session.execute(text("SELECT 1"))).scalar_one() != 1:
                raise SmokeFailure("Connection was not reusable after failure")
            await session.rollback()
    finally:
        await engine.dispose()
    log_ok("real statement timeout read-only denial rollback and connection reuse")


def main():
    asyncio.run(database_checks())
    report = measure(API_BASE_URL, requests=20, concurrency=4)
    if report["status"] != "passed" or report["requests"] != 20:
        raise SmokeFailure("Concurrent readiness probes failed")
    print(json.dumps({"readiness_probe": report}, sort_keys=True))
    log_ok("bounded concurrent HTTP readiness without model calls or document writes")
    print("[success] Operational failure recovery smoke passed.")


if __name__ == "__main__":
    main()
