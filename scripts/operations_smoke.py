import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.readiness import StorageProbe, expected_migration_heads
from app.core.request_observability import REQUEST_ID_PATTERN
from app.db.session import build_database_url
from app.repositories.runtime_health import RuntimeHealthRepository
from app.services.runtime_health import RuntimeReadiness
from scripts.docker_smoke import API_BASE_URL, SmokeFailure, log_ok


def http_checks():
    ids = []
    for path, expected in (("/health", 200), ("/ready", 200), ("/users/me", 401), ("/operations-does-not-exist", 404)):
        request = Request(
            API_BASE_URL + path,
            headers={"X-Request-ID": "synthetic-forged-client-id"},
        )
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            if response.status != expected:
                raise SmokeFailure("Operations HTTP contract failed")
            request_id = response.headers.get("X-Request-ID", "")
            if not REQUEST_ID_PATTERN.fullmatch(request_id):
                raise SmokeFailure("Server correlation header is missing")
            ids.append(request_id)
            if path == "/ready":
                if json.loads(response.read()) != {"status": "ready"}:
                    raise SmokeFailure("Public readiness exposed operator detail")
                if response.headers.get("Cache-Control") != "no-store":
                    raise SmokeFailure("Readiness must not be cached")
    if len(set(ids)) != len(ids):
        raise SmokeFailure("Requests did not receive independent correlation IDs")
    log_ok("real HTTP liveness readiness private errors and correlation")


def operator_checks():
    command = [sys.executable, "-m", "scripts.runtime_diagnostics", "--queues"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    if result.returncode:
        raise SmokeFailure("Operator diagnostics failed")
    report = json.loads(result.stdout)
    if report["status"] != "ready" or report["models_checked"] is not False:
        raise SmokeFailure("Diagnostics mislabeled model or core readiness")
    if set(report["queues"]) != {"extraction", "embedding"}:
        raise SmokeFailure("Queue aggregates are incomplete")
    for queue in report["queues"].values():
        if set(queue) != {"queued", "running", "expired_leases", "oldest_queued_seconds"}:
            raise SmokeFailure("Operator queue report exposed unexpected fields")
    canary = "synthetic-private-credential-" + uuid4().hex
    environment = dict(
        os.environ, AGENTHIRE_POSTGRES_HOST="127.0.0.1",
        AGENTHIRE_POSTGRES_PORT="1", AGENTHIRE_POSTGRES_PASSWORD=canary,
    )
    failed = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=15, check=False)
    if failed.returncode != 1 or json.loads(failed.stdout)["status"] != "not_ready":
        raise SmokeFailure("Database outage was not safely reported")
    if canary in failed.stdout + failed.stderr:
        raise SmokeFailure("Diagnostics exposed a credential")
    log_ok("operator-only aggregate diagnostics and isolated connection failure")


async def postgres_checks():
    # A separate connection/temporary tables cannot alter public queues or workers.
    database = create_async_engine(
        build_database_url(get_settings()), poolclass=NullPool, hide_parameters=True,
    )
    sessions = async_sessionmaker(database, expire_on_commit=False)
    try:
        with TemporaryDirectory(prefix="agenthire-ops-") as directory:
            root = Path(directory)
            preserved = root / (uuid4().hex + ".pdf")
            preserved.write_bytes(b"synthetic private object")
            healthy = RuntimeReadiness(sessions, StorageProbe(root), expected_migration_heads())
            stale = RuntimeReadiness(sessions, StorageProbe(root), frozenset({"not_installed"}))
            missing = RuntimeReadiness(sessions, StorageProbe(root / "missing"), expected_migration_heads())
            try:
                if not (await healthy.snapshot()).ready:
                    raise SmokeFailure("Real database readiness failed")
                wrong = await stale.snapshot()
                if wrong.ready or wrong.schema != "mismatch":
                    raise SmokeFailure("Migration mismatch was not rejected")
                unavailable = await missing.snapshot()
                if unavailable.ready or unavailable.database != "ok":
                    raise SmokeFailure("Storage outage was not isolated from database health")
                if list(root.iterdir()) != [preserved] or preserved.read_bytes() != b"synthetic private object":
                    raise SmokeFailure("Readiness modified an existing object")
            finally:
                await healthy.close()
                await stale.close()
                await missing.close()
        async with database.connect() as connection:
            for table in ("document_extractions", "document_embedding_jobs"):
                await connection.execute(text(
                    f"CREATE TEMP TABLE {table} "
                    "(status text, lease_expires_at timestamptz, created_at timestamptz)"
                ))
                await connection.execute(text(
                    f"INSERT INTO {table} VALUES "
                    "('queued',NULL,now()-interval '1 hour'),"
                    "('running',now()-interval '1 minute',now()),"
                    "('running',now()+interval '1 hour',now())"
                ))
            await connection.commit()
            async with AsyncSession(bind=connection) as session:
                repository = RuntimeHealthRepository(session)
                await repository.configure()
                report = await repository.queues()
            for queue in report.values():
                if (queue["queued"], queue["running"], queue["expired_leases"]) != (1, 2, 1):
                    raise SmokeFailure("Real PostgreSQL queue aggregates were incorrect")
                if queue["oldest_queued_seconds"] < 3600:
                    raise SmokeFailure("Queue age did not use database time")
    finally:
        await database.dispose()
    log_ok("real PostgreSQL migration comparison rollback and private queue aggregates")


def main():
    http_checks()
    operator_checks()
    asyncio.run(postgres_checks())
    print("[success] Operational readiness and request observability smoke passed.")


if __name__ == "__main__":
    main()
