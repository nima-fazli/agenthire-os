"""Guarded AgentHire update installer; standalone copy is included in the ZIP."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

BUNDLE = Path(__file__).resolve().parent
FORBIDDEN = {".git", ".env", ".venv", "storage", "node_modules", "__pycache__"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def normalized(data):
    try:
        return data.decode("utf-8-sig").replace("\r\n", "\n").encode()
    except UnicodeDecodeError:
        return data


def safe_target(project, name):
    relative = PurePosixPath(name)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
        or "\\" in name
        or any(p in FORBIDDEN for p in relative.parts)
    ):
        raise ValueError(
            "Unsafe update path. Private configuration, Git and stored data are protected."
        )
    target = project.joinpath(*relative.parts)
    cursor = target
    while cursor != project:
        if cursor.is_symlink() or cursor.is_junction():
            raise ValueError("Links are not update targets: " + name)
        cursor = cursor.parent
    if not target.resolve().is_relative_to(project):
        raise ValueError("Update target escaped the project.")
    return target


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".agents-update-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            shutil.copymode(path, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def backup_database(project, backup):
    if not shutil.which("docker"):
        raise ValueError(
            "Start Docker and the existing PostgreSQL stack before applying the update."
        )
    prefix = ["docker", "compose", "-f", "compose.yaml"]
    filename = "/tmp/agenthire-agents-" + uuid4().hex + ".dump"
    command = (
        'pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --file='
        + filename
    )

    def run(args):
        result = subprocess.run(
            [*prefix, *args], cwd=project, capture_output=True, timeout=180, check=False
        )
        if result.returncode:
            raise ValueError(
                "Database backup failed. No project files were changed. Start the existing PostgreSQL container and retry."
            )

    try:
        run(["exec", "-T", "postgres", "sh", "-c", command])
        run(["cp", "postgres:" + filename, str(backup / "database.dump")])
        path = backup / "database.dump"
        if (
            not path.is_file()
            or path.stat().st_size < 5
            or path.read_bytes()[:5] != b"PGDMP"
        ):
            raise ValueError(
                "The database backup could not be verified. No project files were changed."
            )
        path.chmod(0o600)
        return {
            "file": "database.dump",
            "sha256": digest(path.read_bytes()),
            "format": "pg_dump_custom",
        }
    finally:
        subprocess.run(
            [*prefix, "exec", "-T", "postgres", "rm", "-f", filename],
            cwd=project,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )


def install(project, apply=False, skip_database_backup=False):
    project = project.resolve()
    if (
        not (project / "pyproject.toml").is_file()
        or not (project / "migrations/versions/0017_access_sessions.py").is_file()
    ):
        raise ValueError(
            "Choose the existing AgentHire OS project with the Bright frontend and migration 0017."
        )
    manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    changes = []
    conflicts = []
    for item in manifest["files"]:
        target, payload = (
            safe_target(project, item["path"]),
            safe_target(BUNDLE / "payload", item["path"]),
        )
        data = payload.read_bytes()
        if digest(data) != item["sha256"]:
            raise ValueError("The update package is damaged: " + item["path"])
        original = target.read_bytes() if target.is_file() else None
        if original is not None and digest(normalized(original)) == digest(
            normalized(data)
        ):
            continue
        expected = item.get("before_normalized_sha256")
        if (
            original is None
            and expected is not None
            or original is not None
            and (expected is None or digest(normalized(original)) != expected)
        ):
            conflicts.append(item["path"])
        changes.append((item["path"], target, data, original))
    if conflicts:
        return {
            "status": "blocked",
            "reason": "Local files differ from the reviewed baseline. Nothing was overwritten.",
            "conflicts": conflicts,
        }
    if not changes:
        return {"status": "up_to_date", "files_changed": 0}
    if not apply:
        return {
            "status": "ready",
            "files_to_change": len(changes),
            "schema": "0017 -> 0018_local_agents",
            "database_backup": "required"
            if not skip_database_backup
            else "skipped_explicitly",
            "private_configuration_preserved": True,
        }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = (
        project.parent
        / "AgentHire_OS_Agent_Backups"
        / ("agents-" + stamp + "-" + uuid4().hex[:8])
    )
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    database = {"status": "skipped_explicitly"}
    if not skip_database_backup:
        print(
            "Backing up the existing PostgreSQL database before changing project files...",
            flush=True,
        )
        database = backup_database(project, backup)
    records = []
    for name, _, _, original in changes:
        if original is not None:
            saved = backup / "files" / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(original)
        records.append(
            {
                "path": name,
                "existed": original is not None,
                "sha256": digest(original) if original is not None else None,
            }
        )
    receipt = {
        "project": str(project),
        "database": database,
        "files": records,
        "database_migrated_by_installer": False,
        "status": "prepared",
    }
    receipt_path = backup / "backup.json"
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    written = []
    try:
        for name, target, data, original in changes:
            current = target.read_bytes() if target.is_file() else None
            if current != original:
                raise ValueError("A file changed during installation: " + name)
            atomic_write(target, data)
            written.append((target, original))
    except BaseException:
        for target, original in reversed(written):
            if original is None:
                target.unlink(missing_ok=True)
            else:
                atomic_write(target, original)
        receipt["status"] = "file_changes_rolled_back"
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        raise
    receipt["status"] = "installed"
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return {
        "status": "installed",
        "files_changed": len(changes),
        "backup": str(backup),
        "database_backup": "saved"
        if not skip_database_backup
        else "skipped_explicitly",
        "private_configuration_preserved": True,
        "next": "docker compose -f compose.yaml -f compose.agents.yaml up -d --build --wait",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--skip-database-backup",
        action="store_true",
        help="Explicitly skip the dump; intended only for empty test copies.",
    )
    args = parser.parse_args(argv)
    try:
        result = install(args.project, args.apply, args.skip_database_backup)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        result = {"status": "failed", "message": str(error)}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] in {"ready", "installed", "up_to_date"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
