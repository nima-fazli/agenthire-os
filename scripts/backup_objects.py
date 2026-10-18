"""Container-only bounded PDF transport and logical database fingerprints."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile

import asyncpg

from app.core.config import get_settings
from app.core.recovery_archive import (
    MAX_ARCHIVE,
    export_objects,
    import_objects,
    verify_objects,
)
from scripts.candidate_document_smoke import connection
from scripts.recovery_objects import read_catalog, require_scope


def authorize(project, action):
    if os.environ.get("AGENTHIRE_BACKUP_PROJECT") != project:
        raise ValueError("Explicit backup scope required.")
    if project != "agenthire-os":
        return require_scope(project)
    settings = get_settings()
    if (action == "import" or settings.environment == "test"
            or settings.postgres_host != "postgres" or settings.postgres_db == "agenthire_ci"
            or settings.postgres_user == "agenthire_ci"):
        raise ValueError("Normal scope only permits reading.")
    return settings


def settings_identity(settings):
    values = [settings.postgres_host, settings.postgres_port, settings.postgres_db,
              settings.postgres_user, settings.postgres_password.get_secret_value(),
              settings.jwt_secret.get_secret_value()]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


async def database_audit():
    await read_catalog()
    database = await connection()
    try:
        async with database.transaction(isolation="repeatable_read", readonly=True):
            for command in (
                "SET LOCAL statement_timeout = '10000ms'", "SET LOCAL lock_timeout = '500ms'",
                "SET LOCAL TIME ZONE 'UTC'", "SET LOCAL datestyle = 'ISO, YMD'",
                "SET LOCAL intervalstyle = 'iso_8601'", "SET LOCAL extra_float_digits = 3",
            ):
                await database.execute(command)
            size = await database.fetchval("SELECT pg_database_size(current_database())")
            if size > 256 * 1024 * 1024:
                raise ValueError("Logical backup database limit exceeded.")
            result = {"schema": "0016_document_embeddings", "postgres_major": 18,
                      "vector_version": await database.fetchval("SELECT extversion FROM pg_extension WHERE extname='vector'"),
                      "tables": [], "sequences": []}
            names = await database.fetch("""
                SELECT c.relname::text AS name, c.relkind::text AS kind FROM pg_class c
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind IN ('r','S') ORDER BY c.relname
            """)
            if len(names) > 128:
                raise ValueError("Backup relation limit exceeded.")
            total = 0
            for row in sorted(names, key=lambda row: row["name"]):
                name = row["name"]
                if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", name):
                    raise ValueError("Unsupported backup relation.")
                if row["kind"] == "S":
                    value = await database.fetchrow(f'SELECT last_value, is_called FROM public."{name}"')
                    result["sequences"].append({"name": name, **dict(value)})
                    continue
                digest, count, hashes = hashlib.sha256(), 0, []
                query = (f'SELECT encode(sha256(convert_to(to_jsonb(t)::text, \'UTF8\')), \'hex\') '
                         f'AS digest FROM public."{name}" AS t')
                async for record in database.cursor(query, prefetch=100):
                    value = record["digest"]
                    if not re.fullmatch(r"[0-9a-f]{64}", value):
                        raise ValueError("Invalid database fingerprint.")
                    hashes.append(value)
                    count += 1
                    total += 1
                    if total > 200000:
                        raise ValueError("Backup row limit exceeded.")
                for value in sorted(hashes):
                    digest.update(value.encode("ascii"))
                result["tables"].append({"name": name, "rows": count, "sha256": digest.hexdigest()})
            fingerprint = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
            return {**result, "fingerprint": fingerprint, "database_bytes": size, "rows": total}
    finally:
        await database.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("audit", "export", "import", "verify"))
    parser.add_argument("--project", required=True)
    args = parser.parse_args(argv)
    try:
        settings = authorize(args.project, args.action)
        if args.action == "audit":
            print(json.dumps({"status": "passed", "settings_identity": settings_identity(settings),
                              "dump_connection": {"database": settings.postgres_db, "user": settings.postgres_user},
                              "database": asyncio.run(database_audit())}, sort_keys=True))
            return 0
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
                        raise ValueError("Backup PDF limit exceeded.")
                    handle.write(chunk)
                handle.seek(0)
                report = import_objects(handle, settings.document_storage_path, rows)
        else:
            report = verify_objects(settings.document_storage_path, rows)
        print(json.dumps({"status": "passed", **report, "database_catalog_matches": True}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, zipfile.BadZipFile,
            asyncpg.PostgresError, asyncpg.InterfaceError):
        print(json.dumps({"status": "failed", "diagnostic": "backup_objects_unavailable"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
