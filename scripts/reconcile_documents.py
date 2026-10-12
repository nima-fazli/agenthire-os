"""Private operator CLI. Dry-run by default; apply only an explicit key list."""

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import asdict

from sqlalchemy.exc import SQLAlchemyError

from app.core.document_reconciliation import MAX_KEYS, ReconciliationError, validate_key
from app.services.document_reconciliation import (
    DocumentReconciliationService,
    ReconciliationOutcome,
)


def managed_key(value: str) -> str:
    try:
        validate_key(value)
    except ReconciliationError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return value


def age_days(value: str) -> int:
    try:
        days = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Age must be an integer.") from error
    if not 1 <= days <= 365:
        raise argparse.ArgumentTypeError("Age must be between 1 and 365 days.")
    return days


async def reconcile(args: argparse.Namespace, emit):
    from app.core.config import get_settings
    from app.core.document_reconciliation import ReconciliationStorage
    from app.db.session import async_session_factory, engine

    try:
        async with async_session_factory() as session:
            service = DocumentReconciliationService(
                session, ReconciliationStorage(get_settings().document_storage_path)
            )
            return await service.run(
                keys=tuple(args.key),
                apply=args.apply,
                min_age_seconds=args.min_age_days * 86_400,
                emit=emit,
            )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", action="append", type=managed_key, default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--min-age-days", type=age_days, default=7)
    args = parser.parse_args(argv)
    if len(args.key) > MAX_KEYS or len(set(args.key)) != len(args.key):
        parser.error("Select at most 200 distinct keys.")
    if args.apply and not args.key:
        parser.error("--apply requires at least one explicit --key.")
    outcomes = []

    def emit(outcome: ReconciliationOutcome) -> None:
        outcomes.append(outcome)
        print(json.dumps({"event": "object", **asdict(outcome)}), flush=True)

    try:
        asyncio.run(reconcile(args, emit))
        failed = any(
            item.action in {"delete_failed", "referenced_missing"} for item in outcomes
        )
        code = 1 if failed else 0
    except (ReconciliationError, SQLAlchemyError, OSError, ValueError, RuntimeError):
        print(
            "Reconciliation failed. Check the journal; completed deletions persist.",
            file=sys.stderr,
        )
        code = 1
    except KeyboardInterrupt:
        code = 130
    print(
        json.dumps(
            {
                "event": "summary",
                "mode": "apply" if args.apply else "dry_run",
                "ok": code == 0,
                "counts": dict(Counter(item.action for item in outcomes)),
            }
        ),
        flush=True,
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
