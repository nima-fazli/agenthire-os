"""Internal PDF snapshot transport for fresh synthetic recovery stacks."""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import zipfile

import asyncpg

from app.core.config import get_settings
from app.core.recovery_archive import (
    MAX_ARCHIVE,
    catalog,
    export_objects,
    import_objects,
    verify_objects,
)
from scripts.candidate_document_smoke import connection
from scripts.ci_plan import validate_project_name


def require_scope(project):
    validate_project_name(project)
    settings = get_settings()
    if (os.environ.get("AGENTHIRE_RECOVERY_PROJECT") != project
            or settings.environment != "test" or settings.postgres_db != "agenthire_ci"
            or settings.postgres_user != "agenthire_ci" or settings.postgres_host != "postgres"):
        raise ValueError("Recovery requires its isolated test scope.")
    return settings


async def read_catalog():
    database = await connection()
    try:
        async with database.transaction(isolation="repeatable_read", readonly=True):
            await database.execute("SET LOCAL statement_timeout = '3000ms'")
            await database.execute("SET LOCAL lock_timeout = '500ms'")
            heads = await database.fetch("SELECT version_num FROM alembic_version")
            version = await database.fetchval("SELECT current_setting('server_version_num')::integer")
            pending = await database.fetchval("""
                SELECT (SELECT count(*) FROM document_extractions WHERE status IN ('queued', 'running'))
                     + (SELECT count(*) FROM document_embedding_jobs WHERE status IN ('queued', 'running'))
                     + (SELECT count(*) FROM candidate_documents WHERE status <> 'ready')
            """)
            if {row["version_num"] for row in heads} != {"0016_document_embeddings"} or not 180000 <= version < 190000 or pending:
                raise ValueError("Recovery source is not settled on the expected schema.")
            rows = await database.fetch("""
                SELECT storage_key AS key, size_bytes AS size, sha256
                FROM candidate_documents ORDER BY storage_key LIMIT 1001
            """)
            return catalog([dict(row) for row in rows])
    finally:
        await database.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "import", "verify"))
    parser.add_argument("--project", required=True)
    args = parser.parse_args(argv)
    try:
        settings = require_scope(args.project)
        rows = asyncio.run(read_catalog())
        if args.action == "export":
            export_objects(settings.document_storage_path, rows, sys.stdout.buffer)
            return 0
        if args.action == "import":
            with tempfile.TemporaryFile() as handle:
                size = 0
                while chunk := sys.stdin.buffer.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_ARCHIVE:
                        raise ValueError("Recovery input limit exceeded.")
                    handle.write(chunk)
                handle.seek(0)
                report = import_objects(handle, settings.document_storage_path, rows)
        else:
            report = verify_objects(settings.document_storage_path, rows)
        print(json.dumps({"status": "passed", **report, "database_catalog_matches": True}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile,
            asyncpg.PostgresError, asyncpg.InterfaceError):
        print(json.dumps({"status": "failed", "diagnostic": "recovery_objects_unavailable"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
