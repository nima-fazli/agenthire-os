"""Opt-in logical DB/PDF recovery rehearsal using two fresh synthetic stacks."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from app.core.recovery_archive import MAX_ARCHIVE, validate_archive
from scripts.ci_plan import (
    cleanup_step,
    compose_prefix,
    new_project_name,
    repository_root,
)
from scripts.ci_verify import isolated_environment, preflight, write_environment

FILES = ("database.dump", "documents.zip")
LIMIT = 256 * 1024 * 1024
STEPS = ("fresh-namespace-preflight", "build-source", "seed-two-tenants", "stop-source-writers",
         "capture-and-seal", "build-target", "require-empty-target", "restore-database",
         "restore-pdfs", "schema-check", "verify-recovered-api", "owned-cleanup")


class RecoveryFailure(Exception):
    pass


def digest(path):
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= LIMIT:
        raise ValueError("Invalid recovery artifact.")
    with path.open("rb") as handle:
        return {"size": path.stat().st_size, "sha256": hashlib.file_digest(handle, "sha256").hexdigest()}


def seal(directory):
    if {path.name for path in directory.iterdir()} != set(FILES):
        raise ValueError("Unexpected recovery bundle entry.")
    with (directory / "database.dump").open("rb") as handle:
        if handle.read(5) != b"PGDMP":
            raise ValueError("Expected PostgreSQL custom archive.")
    with (directory / "documents.zip").open("rb") as handle:
        rows = validate_archive(handle)
    report = {"version": 1, "postgres_major": 18, "schema": "0016_document_embeddings",
              "consistency": "owned_stack_writers_stopped", "synthetic_only": True,
              "objects": len(rows), "files": {name: digest(directory / name) for name in FILES}}
    path = directory / "manifest.json"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        path.chmod(0o600)
        json.dump(report, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return report


def verify_bundle(directory, expected):
    if directory.is_symlink() or {path.name for path in directory.iterdir()} != {*FILES, "manifest.json"}:
        raise ValueError("Invalid recovery bundle.")
    manifest = directory / "manifest.json"
    if manifest.is_symlink() or manifest.stat().st_size > 8192:
        raise ValueError("Invalid recovery manifest.")
    if json.loads(manifest.read_text(encoding="utf-8")) != expected:
        raise ValueError("Recovery manifest changed.")
    if any(digest(directory / name) != expected["files"][name] for name in FILES):
        raise ValueError("Recovery artifact changed.")
    with (directory / "documents.zip").open("rb") as handle:
        if len(validate_archive(handle)) != expected["objects"]:
            raise ValueError("Recovery catalog changed.")


def execute(root, runner=subprocess.run):
    source, target = new_project_name(), new_project_name()
    if source == target:
        raise ValueError("Recovery namespaces must differ.")
    owned, started = [], time.perf_counter()
    report = {"status": "failed", "diagnostic": None, "cleanup": "not_started",
              "normal_stack_touched": False, "models_checked": False,
              "retained_backup": False, "scope": "two_fresh_synthetic_stacks", "phase": "preflight"}

    def call(prefix, environment, arguments, *, timeout=180, output=None, input_file=None):
        report["last_operation"] = next((name for name in (
            "build", "up", "stop", "ps", "pg_dump", "pg_restore", "psql", "alembic",
            "scripts.recovery_objects", "scripts.recovery_fixture") if name in arguments), "compose")
        result = runner((*prefix, *arguments), cwd=root, env=environment, check=False,
                        stdin=input_file if input_file is not None else subprocess.DEVNULL,
                        stdout=output if output is not None else subprocess.PIPE,
                        stderr=subprocess.PIPE, timeout=timeout)
        if result.returncode:
            raise RecoveryFailure("recovery_command_failed")
        if output is not None:
            output.flush()
            os.fsync(output.fileno())
            if not 1 <= output.tell() <= LIMIT:
                raise RecoveryFailure("recovery_artifact_limit")
            return ""
        return result.stdout.decode("utf-8") if isinstance(result.stdout, bytes) else result.stdout

    def smoke(prefix, environment, project, module, action, *, output=None, input_file=None):
        arguments = ("--profile", "smoke", "run", "--rm", "--no-deps", "-T", "--env",
                     "AGENTHIRE_RECOVERY_PROJECT=" + project, "smoke", "python", "-m", module,
                     action, "--project", project)
        if module == "scripts.recovery_fixture":
            arguments += ("--run-id", source[-32:])
        value = call(prefix, environment, arguments, output=output, input_file=input_file)
        if output is not None:
            return None
        result = json.loads(value.splitlines()[-1])
        if result.get("status") != "passed":
            raise RecoveryFailure("recovery_gate_failed")
        return result

    try:
        with tempfile.TemporaryDirectory(prefix="agenthire-recovery-") as temporary:
            directory = Path(temporary).resolve()
            scopes = []
            for project, name in ((source, "source.env"), (target, "target.env")):
                env_file = directory / name
                environment = isolated_environment(os.environ, project, env_file)
                preflight(project, root=root, environment=environment, runner=runner)
                scopes.append((project, env_file, environment))
            # No cleanup ownership is acquired until BOTH namespaces were empty.
            for project, env_file, environment in scopes:
                write_environment(env_file, environment)
                owned.append((compose_prefix(root, project, env_file), environment))
            (src, src_env), (dst, dst_env) = owned
            report["owned_projects"] = [source, target]
            try:
                report["phase"] = "source_prepare"
                print("[recovery] prepare synthetic source", flush=True)
                call(src, src_env, ("--profile", "smoke", "build", "api", "migrate", "extraction-worker", "smoke"), timeout=1200)
                up = ("up", "--detach", "--no-build", "--wait", "--wait-timeout", "180",
                      "--scale", "extraction-worker=2", "api", "extraction-worker")
                call(src, src_env, up, timeout=360)
                smoke(src, src_env, source, "scripts.recovery_fixture", "seed")
                call(src, src_env, ("stop", "--timeout", "150", "api", "extraction-worker"), timeout=360)
                running = call(src, src_env, ("ps", "--status", "running", "--quiet", "api", "extraction-worker"))
                if running.strip():
                    raise RecoveryFailure("recovery_writers_not_stopped")
                report["phase"] = "capture"
                print("[recovery] capture coordinated DB and PDF snapshot", flush=True)
                pg = ("exec", "-T", "postgres")
                version = call(src, src_env, (*pg, "pg_dump", "--version"))
                if not re.search(r"PostgreSQL\) 18\.", version):
                    raise RecoveryFailure("recovery_tool_version")
                partial = directory / "bundle.partial"
                partial.mkdir(mode=0o700)
                database, documents = partial / FILES[0], partial / FILES[1]
                with database.open("xb") as handle:
                    database.chmod(0o600)
                    call(src, src_env, (*pg, "pg_dump", "--format=custom", "--no-privileges",
                                       "--username=agenthire_ci", "--dbname=agenthire_ci"), output=handle)
                with documents.open("xb") as handle:
                    documents.chmod(0o600)
                    smoke(src, src_env, source, "scripts.recovery_objects", "export", output=handle)
                if documents.stat().st_size > MAX_ARCHIVE:
                    raise RecoveryFailure("recovery_artifact_limit")
                running = call(src, src_env, ("ps", "--status", "running", "--quiet", "api", "extraction-worker"))
                if running.strip():
                    raise RecoveryFailure("recovery_writers_restarted")
                expected = seal(partial)
                if expected["objects"] != 2:
                    raise RecoveryFailure("recovery_fixture_incomplete")
                bundle = directory / "bundle"
                partial.rename(bundle)
                verify_bundle(bundle, expected)
                report["phase"] = "target_prepare"
                print("[recovery] restore into empty isolated destination", flush=True)
                call(dst, dst_env, ("--profile", "smoke", "build", "api", "migrate", "extraction-worker", "smoke"), timeout=1200)
                call(dst, dst_env, ("up", "--detach", "--wait", "--wait-timeout", "90", "postgres"))
                tables = call(dst, dst_env, (*pg, "psql", "--no-psqlrc", "--no-password", "--tuples-only", "--no-align",
                                            "--username=agenthire_ci", "--dbname=agenthire_ci", "--command",
                                            "SELECT count(*) FROM pg_tables WHERE schemaname='public'"))
                if tables.strip() != "0":
                    raise RecoveryFailure("recovery_destination_not_empty")
                restore_version = call(dst, dst_env, (*pg, "pg_restore", "--version"))
                if not re.search(r"PostgreSQL\) 18\.", restore_version):
                    raise RecoveryFailure("recovery_tool_version")
                report["phase"] = "restore"
                with (bundle / FILES[0]).open("rb") as handle:
                    call(dst, dst_env, (*pg, "pg_restore", "--no-owner", "--no-privileges", "--exit-on-error",
                                       "--single-transaction", "--username=agenthire_ci", "--dbname=agenthire_ci"), input_file=handle)
                with (bundle / FILES[1]).open("rb") as handle:
                    objects = smoke(dst, dst_env, target, "scripts.recovery_objects", "import", input_file=handle)
                if objects.get("objects") != 2 or objects.get("database_catalog_matches") is not True:
                    raise RecoveryFailure("recovery_object_gate_failed")
                report["phase"] = "verify"
                for action in ("current", "check"):
                    value = call(dst, dst_env, ("run", "--rm", "--no-deps", "migrate", "alembic", action))
                    if action == "current" and "0016_document_embeddings" not in value:
                        raise RecoveryFailure("recovery_schema_changed")
                smoke(dst, dst_env, target, "scripts.recovery_objects", "verify")
                call(dst, dst_env, up, timeout=360)
                fixture = smoke(dst, dst_env, target, "scripts.recovery_fixture", "verify")
                if (fixture.get("documents") != 2 or fixture.get("pdf_downloads_verified") != 2
                        or fixture.get("lexical_retrievals_verified") != 2 or fixture.get("tenant_isolation_verified") is not True
                        or type(fixture.get("embedding_vectors_verified")) is not int or fixture["embedding_vectors_verified"] < 2):
                    raise RecoveryFailure("recovery_api_gate_failed")
                report.update(fixture)
                report.update(status="passed", document_integrity_verified=True, database_restored=True,
                              source_writers_stopped=True, artifact_integrity_verified=True, phase="completed")
            finally:
                cleaned = True
                for prefix, environment in reversed(owned):
                    try:
                        step = cleanup_step(prefix)
                        result = runner(step.command, cwd=root, env=environment, check=False,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, timeout=step.timeout)
                        cleaned = result.returncode == 0 and cleaned
                    except (OSError, subprocess.SubprocessError):
                        cleaned = False
                report["cleanup"] = "completed" if cleaned else "attention"
                if not cleaned:
                    report["status"] = "failed"
                    report["diagnostic"] = "recovery_cleanup_failed"
                    report["phase"] = "cleanup"
    except KeyboardInterrupt:
        report.update(status="interrupted", diagnostic="interrupted")
    except RecoveryFailure as error:
        report["status"] = "failed"
        report["diagnostic"] = report["diagnostic"] or str(error)
    except (OSError, ValueError, KeyError, IndexError, RuntimeError, zipfile.BadZipFile,
            subprocess.SubprocessError):
        report["status"] = "failed"
        report["diagnostic"] = report["diagnostic"] or "recovery_drill_unavailable"
    report["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return report


def main(argv=None, *, runner=subprocess.run):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = repository_root(Path.cwd())
        if not args.execute:
            print(json.dumps({"status": "plan", "steps": STEPS, "requires": "--execute",
                              "normal_stack_touched": False, "retained_backup": False}))
            return 0
        report = execute(root, runner)
    except (OSError, ValueError, RuntimeError):
        report = {"status": "failed", "diagnostic": "recovery_setup_unavailable"}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 130 if report["status"] == "interrupted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
