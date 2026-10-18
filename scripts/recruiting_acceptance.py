"""Verify stage 2; optionally finalize its scoped commits, source ZIP and receipt."""

import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from scripts.source_bundle import checked_path

BASE = "3b58176505d4b6d85d6d908cd268a03256f6e53c"
MANIFEST = "scripts/fixtures/recruiting_stage2_manifest.json"


def content_digest(content):
    content = content.removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")
    return hashlib.sha256(content.rstrip(b"\n") + b"\n").hexdigest()


def digest(path):
    return content_digest(path.read_bytes())


def capture(root, arguments):
    result = subprocess.run(arguments, cwd=root, stdin=subprocess.DEVNULL, capture_output=True,
                            encoding="utf-8", errors="replace", timeout=120, check=False)
    if result.returncode:
        raise RuntimeError(f"command_failed: {arguments[0]}")
    return result.stdout.strip()


def run(root, label, arguments):
    print(f"[run] {label}", flush=True)
    result = subprocess.run(arguments, cwd=root, stdin=subprocess.DEVNULL, check=False)
    if result.returncode:
        raise RuntimeError(f"check_failed: {label}")
    print(f"[ok] {label}", flush=True)


def load_manifest(root):
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8-sig"))
    if (not isinstance(manifest, dict) or manifest.get("version") != "recruiting-stage-2-v1"
            or manifest.get("base_commit") != BASE):
        raise ValueError("invalid_stage_manifest")
    paths = manifest["feature_files"] + manifest["test_files"]
    if not paths or len(paths) != len(set(paths)) or MANIFEST not in paths:
        raise ValueError("invalid_stage_file_list")
    if set(manifest["sha256"]) != set(paths) - {MANIFEST}:
        raise ValueError("incomplete_stage_hashes")
    for name in paths:
        checked_path(name)
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f"missing_or_unsafe_file: {name}")
        if name != MANIFEST and digest(path) != manifest["sha256"][name]:
            raise ValueError(f"file_content_mismatch: {name}")
    return manifest


def verify_baseline(root, manifest):
    if Path(capture(root, ["git", "rev-parse", "--show-toplevel"])).resolve() != root:
        raise ValueError("repository_root_required")
    if capture(root, ["git", "branch", "--show-current"]) != "main":
        raise ValueError("main_branch_required")
    if capture(root, ["git", "rev-parse", "HEAD"]) != BASE:
        raise ValueError("stage_1_commit_required")
    changed = set(capture(root, ["git", "diff", "--name-only", "HEAD", "--"]).splitlines())
    allowed = set(manifest["feature_files"] + manifest["test_files"])
    if changed - allowed:
        raise ValueError("unrelated_tracked_changes_present")


def checks(root):
    python = ["uv", "run", "--locked", "--no-sync"]
    compose = ["docker", "compose"]
    smoke = compose + ["--profile", "smoke", "run", "--rm", "--no-deps", "smoke", "python", "-m"]
    return [
        ("source-whitespace", ["git", "diff", "--check"]),
        ("native-ruff", python + ["ruff", "check", "."]),
        ("native-python", python + ["pytest", "-rs", "-W", "error"]),
        ("native-client", ["node", "--test", *sorted(str(path.relative_to(root)).replace("\\", "/")
                                                  for path in (root / "tests").glob("*.test.mjs"))]),
        ("ci-plan", python + ["python", "-m", "scripts.ci_verify", "--dry-run"]),
        ("isolated-ci-and-cleanup", python + ["python", "-m", "scripts.ci_verify"]),
        ("normal-stack-before", python + ["python", "-m", "scripts.stack_diagnostics"]),
        ("normal-images", compose + ["--profile", "smoke", "build", "api", "smoke"]),
        ("normal-api", compose + ["up", "--detach", "--no-deps", "--no-build", "--wait", "--wait-timeout", "120", "api"]),
        ("normal-workload", smoke + ["scripts.workload_smoke"]),
        ("normal-recruiting-workflow", smoke + ["scripts.recruiter_ui_smoke"]),
        ("normal-stack-after", python + ["python", "-m", "scripts.stack_diagnostics"]),
    ]


def finalize(root, manifest, completed, recovery):
    hashes = []
    for key, message in (
        ("feature_files", "feat: complete recruiting workflow and paginated workspace"),
        ("test_files", "test: verify recruiting pages edits transitions and document controls"),
    ):
        paths = manifest[key]
        run(root, f"stage-{key}", ["git", "add", "--", *paths])
        run(root, f"commit-{key}", ["git", "commit", "--only", "-m", message, "--", *paths])
        hashes.append(capture(root, ["git", "rev-parse", "HEAD"]))
    bundle = json.loads(capture(root, ["uv", "run", "--locked", "--no-sync", "python", "-m",
                                       "scripts.source_bundle", "--execute"]))
    if (bundle.get("status") != "created" or not bundle.get("executed")
            or not bundle.get("working_tree_clean") or bundle.get("commit") != hashes[-1]):
        raise ValueError("source_bundle_acceptance_failed")
    archive_hash = hashlib.sha256(Path(bundle["output"]).read_bytes()).hexdigest()
    if archive_hash != bundle["sha256"]:
        raise ValueError("source_archive_hash_mismatch")
    with zipfile.ZipFile(bundle["output"]) as archive:
        for name, expected in manifest["sha256"].items():
            if content_digest(archive.read("agenthire-os/" + name)) != expected:
                raise ValueError(f"committed_source_mismatch: {name}")
    receipt = ["", "## Stage 2 native acceptance receipt", "",
               f"Timestamp: {datetime.now(UTC).isoformat()}", f"Base commit: {BASE}",
               f"Feature commit: {hashes[0]}", f"Test commit: {hashes[1]}",
               *[f"- {name}: passed" for name in completed],
               f"- Source ZIP: {bundle['output']}", f"- Source SHA-256: {archive_hash}",
               f"- Source files: {bundle['file_count']}",
               "- Live models were not part of this workflow gate; existing flags were preserved.",
               "Next stage: 3 access and sessions. Five stages remain.", ""]
    with recovery.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(receipt))
    run(root, "final-git-status", ["git", "status", "--short"])
    print(json.dumps({"status": "accepted", "stage": 2, "feature_commit": hashes[0],
                      "test_commit": hashes[1], "bundle": bundle, "recovery": str(recovery)}, sort_keys=True))


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
            print(json.dumps({"status": "plan", "stage": 2, "base_commit": BASE,
                              "migration_head": "0016_document_embeddings (head)",
                              "checks": [name for name, _ in planned], "executed": False}, sort_keys=True))
            return 0
        verify_baseline(root, manifest)
        recovery = root.parent / "AgentHire_OS_Recovery_Current.md"
        if args.finalize and (not recovery.is_file() or recovery.is_symlink()):
            raise ValueError("personal_recovery_file_required")
        schema = capture(root, ["uv", "run", "--locked", "--no-sync", "alembic", "heads"])
        if schema != "0016_document_embeddings (head)":
            raise ValueError("unexpected_migration_head")
        print("[ok] migration-head", flush=True)
        completed = ["migration-head"]
        for name, command in planned:
            run(root, name, command)
            completed.append(name)
        if load_manifest(root) != manifest:
            raise ValueError("stage_source_changed_during_verification")
        verify_baseline(root, manifest)
        if args.finalize:
            finalize(root, manifest, completed, recovery)
        else:
            print(json.dumps({"status": "verified", "stage": 2, "checks": completed, "committed": False}))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "diagnostic": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
