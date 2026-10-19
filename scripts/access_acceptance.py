"""Accept stage 3 with a retained pre-migration backup and scoped local commits."""

import argparse
import hashlib
import json
import os
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.core.backup_store import BackupStore, file_digest, read_json, write_json
from scripts.backup_run import capture as backup_capture
from scripts.backup_run import normal_runtime
from scripts.backup_runtime import BackupFailure, resume_recorded, validate_records
from scripts.recruiting_acceptance import capture, content_digest, digest, run
from scripts.source_bundle import bundle as source_bundle
from scripts.source_bundle import checked_path

BASE = "1865a7bae5815a083cfd6ad03a00ad202f08ebc6"
OLD_HEAD, HEAD = "0016_document_embeddings", "0017_access_sessions"
MANIFEST = "scripts/fixtures/access_stage3_manifest.json"
MESSAGES = (
    "feat: add revocable sessions organization roles and private invitations",
    "test: verify access boundaries session lifecycle and upgrade recovery",
)
DATABASE_COMMAND = ('exec psql --no-psqlrc --no-password --tuples-only --no-align '
                    '-U "$POSTGRES_USER" -d "$POSTGRES_DB" --command ')


def database_query(source, sql):
    # SQL is an internal constant; shell variables are quoted and never logged.
    if "'" in sql:
        raise ValueError("unsupported_database_query")
    return source.call(("exec", "-T", "postgres", "sh", "-c", DATABASE_COMMAND + "'" + sql + "'")).strip()


def database_head(source):
    value = database_query(source, "SELECT version_num FROM alembic_version")
    if value not in {OLD_HEAD, HEAD}:
        raise ValueError("unexpected_normal_database_head")
    return value


def load_manifest(root):
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8-sig"))
    if (not isinstance(manifest, dict) or manifest.get("version") != "access-stage-3-v1"
            or manifest.get("base_commit") != BASE):
        raise ValueError("invalid_stage_manifest")
    paths = manifest["feature_files"] + manifest["test_files"]
    if len(paths) != 40 or len(paths) != len(set(paths)) or MANIFEST not in paths:
        raise ValueError("invalid_stage_file_list")
    if set(manifest["sha256"]) != set(paths) - {MANIFEST}:
        raise ValueError("incomplete_stage_hashes")
    for name in paths:
        checked_path(name)
        path = root / name
        if (any(parent.is_symlink() or parent.is_junction() for parent in (path, *path.parents))
                or not path.resolve().is_relative_to(root) or not path.is_file()):
            raise ValueError(f"missing_or_unsafe_file: {name}")
        if name != MANIFEST and digest(path) != manifest["sha256"][name]:
            raise ValueError(f"file_content_mismatch: {name}")
    return manifest


def verify_baseline(root, manifest):
    if Path(capture(root, ["git", "rev-parse", "--show-toplevel"])).resolve() != root:
        raise ValueError("repository_root_required")
    if capture(root, ["git", "branch", "--show-current"]) != "main":
        raise ValueError("main_branch_required")
    if capture(root, ["git", "merge-base", BASE, "HEAD"]) != BASE:
        raise ValueError("accepted_stage_2_base_required")
    commits = capture(root, ["git", "rev-list", "--reverse", BASE + "..HEAD"]).splitlines()
    if len(commits) > 2:
        raise ValueError("unrelated_commits_present")
    groups = (manifest["feature_files"], manifest["test_files"])
    parent = BASE
    for index, commit in enumerate(commits):
        if (capture(root, ["git", "show", "-s", "--format=%P", commit]) != parent
                or capture(root, ["git", "show", "-s", "--format=%s", commit]) != MESSAGES[index]):
            raise ValueError("unexpected_stage_commit")
        names = capture(root, ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit]).splitlines()
        if set(names) != set(groups[index]):
            raise ValueError("unexpected_stage_commit_files")
        for name in names:
            committed = subprocess.run(["git", "show", f"{commit}:{name}"], cwd=root,
                                       stdin=subprocess.DEVNULL, capture_output=True, check=True).stdout
            if content_digest(committed) != digest(root / name):
                raise ValueError("committed_stage_content_changed")
        parent = commit
    changed = set(capture(root, ["git", "diff", "--name-only", "HEAD", "--"]).splitlines())
    untracked = set(capture(root, ["git", "ls-files", "--others", "--exclude-standard"]).splitlines())
    allowed = set(manifest["feature_files"] + manifest["test_files"])
    if (changed | untracked) - allowed:
        raise ValueError("unrelated_source_changes_present")
    return commits


def checks(root):
    python = ["uv", "run", "--locked", "--no-sync"]
    return [
        ("source-whitespace", ["git", "diff", "--check"]),
        ("native-ruff", python + ["ruff", "check", "."]),
        ("native-python", python + ["pytest", "-rs", "-W", "error"]),
        ("native-client", ["node", "--test", *sorted(str(path.relative_to(root)).replace("\\", "/")
                                                  for path in (root / "tests").glob("*.test.mjs"))]),
        ("ci-plan", python + ["python", "-m", "scripts.ci_verify", "--dry-run"]),
        ("isolated-ci-and-cleanup", python + ["python", "-m", "scripts.ci_verify"]),
    ]


def pre_migration_backup(root, source, store):
    """Reuse a verified 0016 receipt on a retry after migration, never overwrite data."""
    pointer = store.root / "receipts" / "stage3-pre-migration.json"
    with store.locked():
        if (store.root / "journal.json").exists():
            resume_recorded(store, source)
        before = database_head(source)
        if before == OLD_HEAD:
            records = source.writers()
            report = {}
            identity = backup_capture(store, source, root / ".env", BASE, "normal", report, prepare=False)
            value = {"base_commit": BASE, "source_schema": OLD_HEAD, "backup_id": identity,
                     "writers": records, "environment": file_digest(root / ".env", 65536),
                     "manifest": file_digest(store.root / identity / "backup.json", 8192)}
            temporary = pointer.with_name(uuid4().hex + ".json")
            write_json(temporary, value)
            os.replace(temporary, pointer)
        else:
            value = read_json(pointer, 8192)
        if set(value) != {"base_commit", "source_schema", "backup_id", "writers", "environment", "manifest"}:
            raise ValueError("invalid_pre_migration_receipt")
        identity = value["backup_id"]
        manifest = store.verify(identity)
        state = read_json(store.root / identity / "state.json", 2048)
        database = read_json(store.root / identity / "database.json")
        validate_records(value["writers"], "agenthire-os")
        if (value["base_commit"] != BASE or value["source_schema"] != OLD_HEAD
                or state.get("source_kind") != "normal" or state.get("revision") != BASE
                or database.get("schema") != OLD_HEAD
                or value["environment"] != file_digest(root / ".env", 65536)
                or value["environment"] != manifest["files"]["source.env"]
                or value["manifest"] != file_digest(store.root / identity / "backup.json", 8192)):
            raise ValueError("pre_migration_backup_mismatch")
    print("[ok] retained-pre-migration-backup " + identity, flush=True)
    return value, before


def normal_upgrade(root, source, receipt, before):
    services = sorted({row["service"] for row in receipt["writers"]})
    source.call(("--profile", "smoke", "build", "migrate", "smoke", *services), timeout=1200)
    print("[ok] normal-images", flush=True)
    if database_head(source) != before:
        raise ValueError("database_changed_before_upgrade")
    records = source.writers() if before == OLD_HEAD else None
    try:
        if records:
            source.call(("stop", "--timeout", "150", *services), timeout=360)
            source.stopped(records)
        source.call(("run", "--rm", "--no-deps", "migrate", "alembic", "upgrade", "head"), timeout=180)
        if database_head(source) != HEAD:
            raise ValueError("normal_migration_head_mismatch")
        source.call(("run", "--rm", "--no-deps", "migrate", "alembic", "check"), timeout=180)
        if before == OLD_HEAD:
            # Existing memberships were ranked by active account then creation order.
            mismatch = database_query(source, """
                WITH ranked AS (
                    SELECT m.role, row_number() OVER (
                        PARTITION BY m.organization_id ORDER BY u.is_active DESC, m.created_at, m.id
                    ) AS position FROM organization_memberships m JOIN users u ON u.id = m.user_id
                ) SELECT count(*) FROM ranked WHERE
                    (position = 1 AND role <> $$owner$$) OR (position > 1 AND role <> $$recruiter$$)
            """)
            if mismatch != "0":
                raise ValueError("owner_backfill_mismatch")
        print("[ok] normal-migration-and-drift", flush=True)
    finally:
        if database_head(source) == HEAD:
            source.call(("up", "--detach", "--no-deps", "--no-build", "--wait", "--wait-timeout", "120",
                         "--scale", "extraction-worker=2", *services), timeout=240)
        elif records:
            source.resume(records)
    run(root, "normal-stack", ["uv", "run", "--locked", "--no-sync", "python", "-m", "scripts.stack_diagnostics"])
    for name in ("workload_smoke", "recruiter_ui_smoke"):
        source.call(("--profile", "smoke", "run", "--rm", "--no-deps", "-T", "smoke", "python", "-m",
                     "scripts." + name), timeout=360)
        print("[ok] normal-" + name, flush=True)
    run(root, "normal-stack-after", ["uv", "run", "--locked", "--no-sync", "python", "-m", "scripts.stack_diagnostics"])


def finalize(root, manifest, completed, recovery, backup):
    hashes = verify_baseline(root, manifest)
    for index, key in enumerate(("feature_files", "test_files")):
        if index < len(hashes):
            continue
        paths = manifest[key]
        run(root, "stage-" + key, ["git", "add", "--", *paths])
        run(root, "commit-" + key, ["git", "commit", "--only", "-m", MESSAGES[index], "--", *paths])
        hashes.append(capture(root, ["git", "rev-parse", "HEAD"]))
    output = Path(source_bundle(root)["output"])
    if output.exists():
        output = output.with_stem(output.stem + "-" + uuid4().hex[:8])
    bundle = source_bundle(root, output, execute=True)
    if (bundle.get("status") != "created" or not bundle.get("executed")
            or not bundle.get("working_tree_clean") or bundle.get("commit") != hashes[-1]):
        raise ValueError("source_bundle_acceptance_failed")
    archive_hash = hashlib.sha256(Path(bundle["output"]).read_bytes()).hexdigest()
    if archive_hash != bundle["sha256"]:
        raise ValueError("source_archive_hash_mismatch")
    with zipfile.ZipFile(bundle["output"]) as archive:
        for name in manifest["feature_files"] + manifest["test_files"]:
            if content_digest(archive.read("agenthire-os/" + name)) != digest(root / name):
                raise ValueError("committed_source_mismatch: " + name)
    receipt = ["", "## Stage 3 native acceptance receipt", "",
               f"Timestamp: {datetime.now(UTC).isoformat()}", f"Base commit: {BASE}",
               f"Feature commit: {hashes[0]}", f"Test commit: {hashes[1]}",
               *[f"- {name}: passed" for name in completed],
               f"- Retained pre-migration backup: {backup}",
               "- Backup uses schema 0016; restore with the accepted stage 2 source.",
               f"- Source ZIP: {bundle['output']}", f"- Source SHA-256: {archive_hash}",
               f"- Source files: {bundle['file_count']}",
               "- Live models and comprehensive browser QA remain later gates.",
               "Next stage: 4 AI quality. Four stages remain.", ""]
    existing = recovery.read_text(encoding="utf-8-sig")
    if f"Test commit: {hashes[1]}" not in existing:
        with recovery.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(receipt))
    run(root, "final-git-status", ["git", "status", "--short"])
    print(json.dumps({"status": "accepted", "stage": 3, "feature_commit": hashes[0],
                      "test_commit": hashes[1], "bundle": bundle, "recovery": str(recovery),
                      "pre_migration_backup": str(backup)}, sort_keys=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args(argv)
    if args.finalize and not args.execute:
        parser.error("--finalize requires --execute")
    root = Path(__file__).resolve().parents[1]
    try:
        manifest = load_manifest(root)
        planned = checks(root)
        if not args.execute:
            print(json.dumps({"status": "plan", "stage": 3, "base_commit": BASE,
                              "migration_from": OLD_HEAD, "migration_to": HEAD,
                              "checks": [name for name, _ in planned] + [
                                  "retained-pre-migration-backup", "normal-migration-and-drift",
                                  "normal-workload", "normal-access-and-recruiting-http", "normal-stack-after"],
                              "executed": False}, sort_keys=True))
            return 0
        verify_baseline(root, manifest)
        recovery = root.parent / "AgentHire_OS_Recovery_Current.md"
        if not recovery.is_file() or recovery.is_symlink() or recovery.is_junction():
            raise ValueError("personal_recovery_file_required")
        schema = capture(root, ["uv", "run", "--locked", "--no-sync", "alembic", "heads"])
        if schema != HEAD + " (head)":
            raise ValueError("unexpected_source_migration_head")
        completed = ["source-migration-head"]
        for name, command in planned:
            run(root, name, command)
            completed.append(name)
        if load_manifest(root) != manifest:
            raise ValueError("stage_source_changed_during_verification")
        verify_baseline(root, manifest)
        source = normal_runtime(root)
        store = BackupStore(root.parent / "AgentHire_OS_Backups", root)
        if not store.root.exists():
            store.initialize()
        receipt, before = pre_migration_backup(root, source, store)
        normal_upgrade(root, source, receipt, before)
        completed += ["retained-pre-migration-backup", "normal-migration-and-drift",
                      "normal-workload", "normal-access-and-recruiting-http", "normal-stack-after"]
        if load_manifest(root) != manifest:
            raise ValueError("stage_source_changed_during_verification")
        verify_baseline(root, manifest)
        backup = store.root / receipt["backup_id"]
        if args.finalize:
            finalize(root, manifest, completed, recovery, backup)
        else:
            print(json.dumps({"status": "verified", "stage": 3, "checks": completed, "committed": False,
                              "pre_migration_backup": str(backup)}, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "diagnostic": "rerun_stage_gate_to_resume"}))
        return 130
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError,
            zipfile.BadZipFile, BackupFailure) as error:
        print(json.dumps({"status": "failed", "diagnostic": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
