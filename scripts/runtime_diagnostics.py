"""Local operator diagnostics; storage writes only an ephemeral probe file."""

import argparse
import asyncio
import json
import sys

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.readiness import StorageProbe, expected_migration_heads
from app.repositories.runtime_health import RuntimeHealthRepository
from app.services.runtime_health import RuntimeReadiness


async def collect(*, queues: bool = False) -> dict:
    from app.db.session import async_session_factory, engine

    settings = get_settings()
    configure_logging(level=settings.log_level, stream=sys.stderr)
    probe = RuntimeReadiness(
        async_session_factory, StorageProbe(settings.document_storage_path),
        expected_migration_heads(),
    )
    try:
        snapshot = await probe.snapshot()
        report = {
            "status": "ready" if snapshot.ready else "not_ready",
            "components": snapshot.operator_report(),
            "features": {
                "semantic_enabled": settings.semantic_enabled,
                "explanations_enabled": settings.explanations_enabled,
            },
            "models_checked": False,
        }
        if queues:
            report["queues"] = await queue_report(async_session_factory)
        return report
    finally:
        await probe.close()
        await engine.dispose()


async def queue_report(session_factory):
    try:
        async with asyncio.timeout(2):
            async with session_factory() as session:
                repository = RuntimeHealthRepository(session)
                await repository.configure()
                return await repository.queues()
    except (SQLAlchemyError, OSError, TimeoutError):
        return "unavailable"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queues", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(collect(queues=args.queues))
    except (SQLAlchemyError, OSError, ValueError, RuntimeError):
        report = {"status": "not_ready", "diagnostic": "unavailable"}
    except KeyboardInterrupt:
        return 130
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "ready" and report.get("queues") != "unavailable" else 1


if __name__ == "__main__":
    raise SystemExit(main())
