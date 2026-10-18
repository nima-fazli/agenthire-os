"""Retain a private normal-data backup; restore only into a fresh isolated stack."""

import argparse
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from app.core.backup_store import (
    BackupStore,
    file_digest,
    open_private,
    read_json,
    write_json,
)
from scripts.backup_runtime import (
    IDENTITY_CODE,
    BackupFailure,
    Runtime,
    record_pause,
    resume_recorded,
)
from scripts.ci_plan import (
    cleanup_step,
    compose_prefix,
    new_project_name,
    repository_root,
)
from scripts.ci_verify import isolated_environment, preflight, write_environment

BASELINE = "07778952be9ff9a6fd86064a3fa2c7dcd048c824"


def normal_runtime(root, *, runner=subprocess.run):
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(("AGENTHIRE_", "COMPOSE_"))}
    prefix = ("docker", "compose", "--project-name", "agenthire-os", "--profile", "semantic",
              "--env-file", str(root / ".env"), "--file", str(root / "compose.yaml"))
    return Runtime(root, "agenthire-os", prefix, environment, runner=runner)


def capture(store, source, environment_file, revision, source_kind, report):
    if source_kind not in {"normal", "synthetic"} or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Invalid backup provenance.")
    if (source_kind == "normal") != (source.project == "agenthire-os"):
        raise ValueError("Backup source scope mismatch.")
    before_env = file_digest(environment_file, 65536)
    source.call(("--profile", "smoke", "build", "smoke"), timeout=1200)
    records = source.writers()
    observed = source.call(("exec", "-T", "api", "python", "-c", IDENTITY_CODE)).strip()
    if not re.fullmatch(r"[0-9a-f]{64}", observed):
        raise ValueError("Source settings identity unavailable.")
    first = source.helper("audit")
    if first["settings_identity"] != observed:
        raise ValueError("Running API and source configuration disagree.")
    connection = first["dump_connection"]
    if (not isinstance(connection, dict) or set(connection) != {"database", "user"}
            or any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,62}", value)
                   for value in connection.values())):
        raise ValueError("Unsupported dump connection identifiers.")
    identity, directory = store.new(source_kind=source_kind, revision=revision)
    report.update(backup_id=identity, retained_backup=False, source_resume="not_needed", phase="capture",
                  normal_stack_touched=source_kind == "normal")
    journal = record_pause(store, source, records)
    try:
        services = sorted({row["service"] for row in records})
        source.call(("stop", "--timeout", "150", *services), timeout=360)
        source.stopped(records)
        database = source.helper("audit")["database"]
        write_json(directory / "database.json", database)
        with open_private(environment_file) as origin, open_private(directory / "source.env", "wb") as target:
            data = origin.read(65537)
            if len(data) > 65536:
                raise ValueError("Source environment limit exceeded.")
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        if file_digest(directory / "source.env", 65536) != before_env or file_digest(environment_file, 65536) != before_env:
            raise ValueError("Source environment changed.")
        version = source.call(("exec", "-T", "postgres", "pg_dump", "--version"))
        if not re.search(r"PostgreSQL\) 18\.", version):
            raise ValueError("PostgreSQL 18 dump tool required.")
        with open_private(directory / "database.dump", "wb") as handle:
            source.call(("exec", "-T", "postgres", "pg_dump", "--format=custom", "--no-privileges", "--no-password",
                         "--username=" + connection["user"], "--dbname=" + connection["database"]), output=handle)
        with open_private(directory / "documents.zip", "wb") as handle:
            source.helper("export", output=handle)
        source.stopped(records)
        if source.helper("audit")["database"]["fingerprint"] != database["fingerprint"]:
            raise ValueError("Database changed during capture.")
        store.seal(identity)
        report.update(retained_backup=True, integrity_verified=True, phase="source_resume")
    finally:
        report["source_resume"] = "attention"
        source.resume(records)
        report["source_resume"] = "completed"
        if read_json(store.root / "journal.json", 8192) != journal:
            raise ValueError("Recorded pause changed; source was resumed.")
        (store.root / "journal.json").unlink()
    report.update(status="passed", phase="completed", source_kind=source_kind,
                  database_rows=database["rows"], models_checked=False)
    return identity


def restore(store, identity, root, report, *, runner=subprocess.run, fixture_seed=None):
    if (store.root / "journal.json").exists():
        raise ValueError("Resume the recorded source before restore.")
    store.verify(identity)
    directory = store.root / identity
    expected = read_json(directory / "database.json")
    project, owned = new_project_name(), False
    report.update(backup_id=identity, retained_backup=True, normal_stack_touched=False,
                  cleanup="not_started", phase="target_prepare")
    with tempfile.TemporaryDirectory(prefix="agenthire-backup-restore-") as temporary:
        env_file = Path(temporary).resolve() / "target.env"
        environment = isolated_environment(os.environ, project, env_file)
        preflight(project, root=root, environment=environment, runner=runner)
        write_environment(env_file, environment)
        target = Runtime(root, project, compose_prefix(root, project, env_file), environment, runner=runner)
        owned = True
        report["owned_project"] = project
        try:
            target.call(("--profile", "smoke", "build", "api", "migrate", "extraction-worker", "smoke"), timeout=1200)
            target.call(("up", "--detach", "--wait", "--wait-timeout", "90", "postgres"))
            pg = ("exec", "-T", "postgres")
            tables = target.call((*pg, "psql", "--no-psqlrc", "--no-password", "--tuples-only", "--no-align",
                                  "--username=agenthire_ci", "--dbname=agenthire_ci", "--command",
                                  "SELECT count(*) FROM pg_tables WHERE schemaname='public'"))
            if tables.strip() != "0":
                raise ValueError("Backup destination must be empty.")
            if not re.search(r"PostgreSQL\) 18\.", target.call((*pg, "pg_restore", "--version"))):
                raise ValueError("PostgreSQL 18 restore tool required.")
            store.verify(identity)
            report["phase"] = "restore"
            with open_private(directory / "database.dump") as handle:
                target.call((*pg, "pg_restore", "--no-owner", "--no-privileges", "--no-password", "--exit-on-error",
                             "--single-transaction", "--username=agenthire_ci", "--dbname=agenthire_ci"), input_file=handle)
            with open_private(directory / "documents.zip") as handle:
                target.helper("import", input_file=handle)
            actual = target.helper("audit")["database"]
            if actual["fingerprint"] != expected["fingerprint"]:
                raise ValueError("Restored database contents disagree.")
            for action in ("current", "check"):
                value = target.call(("run", "--rm", "--no-deps", "migrate", "alembic", action))
                if action == "current" and "0016_document_embeddings" not in value:
                    raise ValueError("Restored schema mismatch.")
            objects = target.helper("verify")
            target.call(("up", "--detach", "--no-build", "--no-deps", "--wait", "--wait-timeout", "90", "api"))
            if fixture_seed is not None:
                text = target.call(("--profile", "smoke", "run", "--rm", "--no-deps", "-T",
                                    "--env", "AGENTHIRE_RECOVERY_PROJECT=" + project, "smoke", "python", "-m",
                                    "scripts.recovery_fixture", "verify", "--project", project, "--run-id", fixture_seed))
                if json.loads(text.splitlines()[-1]).get("status") != "passed":
                    raise ValueError("Restored fixture failed.")
            report.update(database_integrity_verified=True, document_integrity_verified=True,
                          api_ready=True, documents=objects["objects"], database_rows=actual["rows"])
        finally:
            if owned:
                step = cleanup_step(target.prefix)
                report["cleanup"] = "attention"
                target.raw(step.command, timeout=step.timeout)
                report["cleanup"] = "completed"
    store.receipt(identity)
    report.update(status="passed", phase="completed", restore_receipt_created=True, models_checked=False)


def main(argv=None, *, runner=subprocess.run):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "list", "verify", "prune", "capture", "restore", "resume"))
    parser.add_argument("--store", required=True)
    parser.add_argument("--backup")
    parser.add_argument("--keep", type=int, default=3)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    report = {"status": "failed", "action": args.action, "models_checked": False}
    try:
        root = repository_root(Path.cwd())
        store = BackupStore(args.store, root)
        if args.action in {"verify", "restore"} and args.backup is None:
            raise ValueError("An exact backup identity is required.")
        if args.action in {"init", "capture", "restore", "resume"} and not args.execute:
            report.update(status="plan", requires="--execute", source_pause=args.action == "capture",
                          restore_destination="fresh_isolated_stack", backup_created=False)
        elif args.action == "init":
            store.initialize()
            report.update(status="passed", private_store_initialized=True)
        else:
            with store.locked():
                if args.action == "list":
                    report.update(status="passed", backups=store.inventories(),
                                  partials=sum(p.name.endswith(".partial") for p in store.root.iterdir()),
                                  resume_required=(store.root / "journal.json").exists())
                elif args.action == "verify":
                    store.verify(args.backup)
                    report.update(status="passed", backup_id=args.backup, integrity_verified=True)
                elif args.action == "prune":
                    report.update(status="passed", **store.prune(args.keep, execute=args.execute))
                elif args.action == "restore":
                    restore(store, args.backup, root, report, runner=runner)
                else:
                    source = normal_runtime(root, runner=runner)
                    if args.action == "resume":
                        resume_recorded(store, source)
                        report.update(status="passed", source_resume="completed")
                    else:
                        source.raw(("git", "merge-base", "--is-ancestor", BASELINE, "HEAD"))
                        if source.raw(("git", "branch", "--show-current")).strip() != "main":
                            raise ValueError("Expected main.")
                        revision = source.raw(("git", "rev-parse", "HEAD")).strip()
                        capture(store, source, root / ".env", revision, "normal", report)
    except KeyboardInterrupt:
        report.update(status="interrupted", diagnostic="operation_interrupted")
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, zipfile.BadZipFile,
            subprocess.SubprocessError, BackupFailure):
        report.update(status="failed", diagnostic="backup_operation_unavailable")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] in {"passed", "plan"} else 130 if report["status"] == "interrupted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
