"""Accept stage 4 only after live model evaluation and successful owned cleanup."""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scripts.access_acceptance import checks, database_head
from scripts.ai_quality_contract import load_reference
from scripts.ai_quality_metrics import validate_report
from scripts.ai_quality_run import execute, save_report
from scripts.ai_quality_run import plan as quality_plan
from scripts.backup_run import normal_runtime
from scripts.ci_plan import new_project_name, validate_project_name
from scripts.ci_verify import isolated_environment, preflight, write_environment
from scripts.evaluation_report import read_json
from scripts.recruiting_acceptance import capture, content_digest, digest, run
from scripts.source_bundle import bundle as source_bundle
from scripts.source_bundle import checked_path

BASE = "261dd607b740a8d91d0bafabe2cb268c276c1c75"
HEAD = "0017_access_sessions"
MANIFEST = "scripts/fixtures/quality_stage4_manifest.json"
MAX_STAGE_FILES = 64
MESSAGES = ("feat: add bilingual local AI quality reference and isolated live gates",
            "test: verify independent AI quality metrics provenance and acceptance")


def load_manifest(root):
    value = read_json(root / MANIFEST)
    if value.get("version") != "quality-stage-4-v1" or value.get("base_commit") != BASE:
        raise ValueError("invalid_quality_manifest")
    paths = value["feature_files"] + value["test_files"]
    if (not 20 <= len(paths) <= MAX_STAGE_FILES or len(paths) != len(set(paths)) or MANIFEST not in paths
            or set(value["sha256"]) != set(paths) - {MANIFEST}):
        raise ValueError("invalid_quality_file_list")
    for name in paths:
        checked_path(name)
        path = root / name
        if not path.is_file():
            raise ValueError("missing_quality_source: " + name)
        if (any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))
                or not path.resolve().is_relative_to(root)):
            raise ValueError("unsafe_quality_source: " + name)
        if name != MANIFEST and digest(path) != value["sha256"][name]:
            raise ValueError("quality_source_mismatch: " + name)
    return value


def verify_baseline(root, manifest):
    if (Path(capture(root, ["git", "rev-parse", "--show-toplevel"])).resolve() != root
            or capture(root, ["git", "branch", "--show-current"]) != "main"
            or capture(root, ["git", "merge-base", BASE, "HEAD"]) != BASE):
        raise ValueError("accepted_stage3_main_required")
    commits = capture(root, ["git", "rev-list", "--reverse", BASE + "..HEAD"]).splitlines()
    if len(commits) > 2:
        raise ValueError("unrelated_commits_present")
    parent = BASE
    for index, commit in enumerate(commits):
        expected = manifest[("feature_files", "test_files")[index]]
        if (capture(root, ["git", "show", "-s", "--format=%P", commit]) != parent
                or capture(root, ["git", "show", "-s", "--format=%s", commit]) != MESSAGES[index]
                or set(capture(root, ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit]).splitlines()) != set(expected)):
            raise ValueError("unexpected_quality_commit")
        for name in expected:
            data = subprocess.run(["git", "show", f"{commit}:{name}"], cwd=root, capture_output=True,
                                  check=True, timeout=30, stdin=subprocess.DEVNULL).stdout
            if content_digest(data) != digest(root / name):
                raise ValueError("committed_quality_content_changed")
        parent = commit
    changed = set(capture(root, ["git", "diff", "--name-only", "HEAD", "--"]).splitlines())
    changed |= set(capture(root, ["git", "ls-files", "--others", "--exclude-standard"]).splitlines())
    if changed - set(manifest["feature_files"] + manifest["test_files"]):
        raise ValueError("unrelated_source_changes_present")
    return commits


def live_gate(root):
    project = new_project_name()
    with tempfile.TemporaryDirectory(prefix="agenthire-quality-") as directory:
        env_file = Path(directory).resolve() / "quality.env"
        environment = isolated_environment(os.environ, project, env_file)
        preflight(project, root=root, environment=environment)
        write_environment(env_file, environment)
        report = asyncio.run(execute(root, project, env_file, environment))
    saved = save_report(root.parent / "AgentHire_OS_Quality_Reports", report)
    print(json.dumps({"quality_status": report["status"], "report": saved}, sort_keys=True), flush=True)
    validate_report(load_reference(), report["measurement"], require_live=True)
    if report["status"] != "passed" or report["cleanup"] != "completed":
        raise ValueError("quality_execution_or_cleanup_failed")
    return saved


def verify_saved_quality(root, saved):
    path = Path(saved["path"])
    if path.parent != root.parent / "AgentHire_OS_Quality_Reports" or path.is_symlink() or path.is_junction():
        raise ValueError("unexpected_quality_report_path")
    with path.open("rb") as handle:
        raw = handle.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != saved["sha256"]:
        raise ValueError("quality_report_hash_mismatch")
    report = read_json(path)
    validate_project_name(report["project"])
    _, steps = quality_plan(root, report["project"], root / "UNUSED_ENV_PATH")
    if (report["version"] != "ai-quality-run-v1" or report["status"] != "passed"
            or report["cleanup"] != "completed" or report["diagnostic"] is not None
            or report["checks"] != [{"name": name, "exit": 0} for name, _, _ in steps]):
        raise ValueError("quality_run_receipt_incomplete")
    validate_report(load_reference(), report["measurement"], require_live=True)


def refresh_normal_workspace(root, source):
    source.call(("--profile", "smoke", "build", "api", "smoke"), timeout=1200)
    source.call(("up", "--detach", "--no-deps", "--no-build", "--wait", "--wait-timeout", "120", "api"), timeout=240)
    source.call(("--profile", "smoke", "run", "--rm", "--no-deps", "-T", "smoke", "python", "-m",
                 "scripts.recruiter_ui_smoke"), timeout=360)
    print("[ok] normal-english-workspace", flush=True)


def append_receipts(recovery, receipt, commit):
    targets = [recovery]
    complete = recovery.with_name("AgentHire_OS_Recovery_Complete.md")
    if complete.exists():
        targets.append(complete)
    for path in targets:
        if not path.is_file() or path.is_symlink() or path.is_junction():
            raise ValueError("unsafe_recovery_file")
    for path in targets:
        if f"Test commit: {commit}" not in path.read_text(encoding="utf-8-sig"):
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(receipt))


def finalize(root, manifest, completed, recovery, quality):
    verify_saved_quality(root, quality)
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
    archive_hash = hashlib.sha256(Path(bundle["output"]).read_bytes()).hexdigest()
    if bundle["commit"] != hashes[-1] or bundle["status"] != "created" or archive_hash != bundle["sha256"]:
        raise ValueError("quality_source_bundle_failed")
    with zipfile.ZipFile(bundle["output"]) as archive:
        for name in manifest["feature_files"] + manifest["test_files"]:
            if content_digest(archive.read("agenthire-os/" + name)) != digest(root / name):
                raise ValueError("quality_bundle_content_mismatch")
    receipt = ["", "## Stage 4 native acceptance receipt", "", f"Timestamp: {datetime.now(UTC).isoformat()}",
               f"Accepted stage 3 base: {BASE}", f"Feature commit: {hashes[0]}", f"Test commit: {hashes[1]}",
               *[f"- {name}: passed" for name in completed], f"- Live quality report: {quality['path']}",
               f"- Quality report SHA-256: {quality['sha256']}", f"- Source ZIP: {bundle['output']}",
               f"- Source SHA-256: {archive_hash}", f"- Source files: {bundle['file_count']}",
               "- Evaluation uses synthetic data and does not establish population-wide quality or fairness.",
               "Next stage: 5, final English product design. Three stages remain.", ""]
    append_receipts(recovery, receipt, hashes[1])
    print(json.dumps({"status": "accepted", "stage": 4, "feature_commit": hashes[0], "test_commit": hashes[1],
                      "bundle": bundle, "quality_report": quality, "recovery": str(recovery)}, sort_keys=True))


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
            print(json.dumps({"status": "plan", "stage": 4, "base_commit": BASE, "schema": HEAD,
                              "checks": [name for name, _ in planned] + ["normal-stack-before", "live-quality-and-cleanup",
                                                                         "normal-english-workspace", "normal-stack-after"],
                              "executed": False}, sort_keys=True))
            return 0
        verify_baseline(root, manifest)
        recovery = root.parent / "AgentHire_OS_Recovery_Current.md"
        if args.finalize and (not recovery.is_file() or recovery.is_symlink() or recovery.is_junction()):
            raise ValueError("personal_recovery_file_required")
        source = normal_runtime(root)
        if database_head(source) != HEAD or capture(root, ["uv", "run", "--locked", "--no-sync", "alembic", "heads"]) != HEAD + " (head)":
            raise ValueError("accepted_stage3_schema_required")
        completed = []
        diagnostics = ["uv", "run", "--locked", "--no-sync", "python", "-m", "scripts.stack_diagnostics"]
        run(root, "normal-stack-before", diagnostics)
        completed.append("normal-stack-before")
        for name, arguments in planned:
            run(root, name, arguments)
            completed.append(name)
        quality = live_gate(root)
        completed.append("live-quality-and-cleanup")
        refresh_normal_workspace(root, source)
        completed.append("normal-english-workspace")
        run(root, "normal-stack-after", diagnostics)
        completed.append("normal-stack-after")
        if load_manifest(root) != manifest:
            raise ValueError("quality_source_changed_during_verification")
        verify_baseline(root, manifest)
        verify_saved_quality(root, quality)
        if args.finalize:
            finalize(root, manifest, completed, recovery, quality)
        else:
            print(json.dumps({"status": "verified", "stage": 4, "committed": False, "quality_report": quality}, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile):
        print(json.dumps({"status": "failed", "diagnostic": "quality_acceptance_incomplete"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
