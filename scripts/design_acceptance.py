"""Accept stage 5 after native regression, isolated CI, and real Chromium checks."""

import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scripts.design_contract import BASE, digest, load_manifest, source_digest

MESSAGES = ("feat: refine the English recruiting workspace and accessible navigation",
            "test: verify responsive design keyboard flows and stage 5 acceptance")
BROWSER_CHECKS = {
    "application-candidate-navigation", "confirmation-cancel-focus", "public-sign-in-and-labels", "signed-in-context", "navigation-setup", "navigation-applications",
    "navigation-access", "navigation-account", "navigation-review", "layout-1440", "layout-1024",
    "layout-768", "layout-390", "layout-320", "keyboard-guide-open", "modal-focus-contained",
    "keyboard-guide-close", "empty-search-state", "safe-error-notification",
    "context-switch-clears-private-dossier", "sign-out-clears-private-shell", "no-uncaught-browser-exceptions",
}


def capture(root, arguments):
    return subprocess.run(arguments, cwd=root, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, check=True, timeout=60).stdout.strip()


def verify_baseline(root, manifest):
    if (Path(capture(root, ["git", "rev-parse", "--show-toplevel"])).resolve() != root
            or capture(root, ["git", "branch", "--show-current"]) != "main"
            or capture(root, ["git", "merge-base", BASE, "HEAD"]) != BASE):
        raise ValueError("accepted_stage4_main_required")
    commits = capture(root, ["git", "rev-list", "--reverse", BASE + "..HEAD"]).splitlines()
    if len(commits) > 2:
        raise ValueError("unrelated_design_commits")
    parent = BASE
    for index, commit in enumerate(commits):
        paths = manifest[("feature_files", "test_files")[index]]
        if (capture(root, ["git", "show", "-s", "--format=%P", commit]) != parent
                or capture(root, ["git", "show", "-s", "--format=%s", commit]) != MESSAGES[index]
                or set(capture(root, ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit]).splitlines()) != set(paths)):
            raise ValueError("unexpected_design_commit")
        for name in paths:
            data = subprocess.run(["git", "show", f"{commit}:{name}"], cwd=root, capture_output=True,
                                  stdin=subprocess.DEVNULL, check=True, timeout=30).stdout
            canonical = data.removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")
            if hashlib.sha256(canonical).hexdigest() != digest(root / name):
                raise ValueError("committed_design_content_changed")
        parent = commit
    changed = set(capture(root, ["git", "diff", "--name-only", "HEAD", "--"]).splitlines())
    changed |= set(capture(root, ["git", "ls-files", "--others", "--exclude-standard"]).splitlines())
    if changed - set(manifest["feature_files"] + manifest["test_files"]):
        raise ValueError("unrelated_design_source_changes")
    return commits


def verify_browser_report(path, expected):
    if not path.is_file() or path.is_symlink() or path.is_junction() or path.stat().st_size > 65536:
        raise ValueError("unsafe_design_report")
    raw = path.read_bytes()
    report = json.loads(raw)
    checks = report.get("checks", [])
    if (report.get("version") != "design-browser-v1" or report.get("source_kind") != "browser_synthetic_fixture"
            or report.get("source_sha256") != expected or report.get("status") != "passed"
            or report.get("cleanup") != "completed" or report.get("diagnostic") is not None
            or not isinstance(report.get("browser"), str) or not report["browser"]
            or len(checks) != len(BROWSER_CHECKS)
            or {row.get("name") for row in checks} != BROWSER_CHECKS
            or any(row.get("passed") is not True for row in checks)):
        raise ValueError("design_browser_acceptance_incomplete")
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def checks(root, report):
    uv = ["uv", "run", "--locked", "--no-sync"]
    return [
        ("native-ruff", uv + ["ruff", "check", "."]),
        ("native-python", uv + ["pytest", "-rs", "-W", "error"]),
        ("native-client", ["node", "--test", *sorted(str(p.relative_to(root)).replace("\\", "/")
                                                    for p in (root / "tests").glob("*.test.mjs"))]),
        ("isolated-ci-and-cleanup", uv + ["python", "-m", "scripts.ci_verify"]),
        ("real-browser-design", ["node", "scripts/design_browser.mjs", "--report", str(report)]),
    ]


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
        fingerprint = source_digest(root)
        report_path = root.parent / "AgentHire_OS_Design_Reports" / ("design-" + uuid4().hex + ".json")
        planned = checks(root, report_path)
        if not args.execute:
            print(json.dumps({"status": "plan", "stage": 5, "base_commit": BASE, "source_sha256": fingerprint,
                              "executed": False, "checks": [name for name, _ in planned]
                              + ["normal-stack-before", "normal-english-workspace", "normal-stack-after"]}))
            return 0
        verify_baseline(root, manifest)
        recovery = root.parent / "AgentHire_OS_Recovery_Current.md"
        if args.finalize and (not recovery.is_file() or recovery.is_symlink() or recovery.is_junction()):
            raise ValueError("personal_recovery_file_required")
        from scripts.access_acceptance import database_head
        from scripts.ai_quality_acceptance import (
            append_receipts,
            refresh_normal_workspace,
        )
        from scripts.backup_run import normal_runtime
        from scripts.recruiting_acceptance import run
        from scripts.source_bundle import bundle

        source = normal_runtime(root)
        if database_head(source) != "0017_access_sessions":
            raise ValueError("accepted_stage4_schema_required")
        diagnostics = ["uv", "run", "--locked", "--no-sync", "python", "-m", "scripts.stack_diagnostics"]
        completed = []
        run(root, "normal-stack-before", diagnostics)
        completed.append("normal-stack-before")
        for name, arguments in planned:
            run(root, name, arguments)
            completed.append(name)
        saved = verify_browser_report(report_path, fingerprint)
        refresh_normal_workspace(root, source)
        completed.append("normal-english-workspace")
        run(root, "normal-stack-after", diagnostics)
        completed.append("normal-stack-after")
        if source_digest(root) != fingerprint or load_manifest(root) != manifest:
            raise ValueError("design_source_changed_during_verification")
        verify_browser_report(report_path, fingerprint)
        commits = verify_baseline(root, manifest)
        result = {"status": "verified", "stage": 5, "browser_report": saved, "committed": False}
        if args.finalize:
            for index, key in enumerate(("feature_files", "test_files")):
                if index < len(commits):
                    continue
                run(root, "stage-" + key, ["git", "add", "--", *manifest[key]])
                run(root, "commit-" + key, ["git", "commit", "--only", "-m", MESSAGES[index], "--", *manifest[key]])
                commits.append(capture(root, ["git", "rev-parse", "HEAD"]))
            output = Path(bundle(root)["output"])
            if output.exists():
                output = output.with_stem(output.stem + "-" + uuid4().hex[:8])
            exported = bundle(root, output, execute=True)
            with zipfile.ZipFile(exported["output"]) as archive:
                for name in manifest["feature_files"] + manifest["test_files"]:
                    raw = archive.read("agenthire-os/" + name).removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")
                    if hashlib.sha256(raw).hexdigest() != digest(root / name):
                        raise ValueError("design_bundle_content_mismatch")
            receipt = ["", "## Stage 5 native acceptance receipt", "", f"Timestamp: {datetime.now(UTC).isoformat()}",
                       f"Accepted stage 4 base: {BASE}", f"Feature commit: {commits[0]}", f"Test commit: {commits[1]}",
                       *[f"- {name}: passed" for name in completed], f"- Browser report: {saved['path']}",
                       f"- Browser report SHA-256: {saved['sha256']}", f"- Source ZIP: {exported['output']}",
                       f"- Source SHA-256: {exported['sha256']}", "- Browser coverage uses synthetic transport, not real applicant data.",
                       "- CI separately verifies the real PostgreSQL, PDF, worker, and HTTP contracts.",
                       "Next stage: 6, release acceptance. Two stages remain.", ""]
            append_receipts(recovery, receipt, commits[1])
            result.update(status="accepted", committed=True, feature_commit=commits[0], test_commit=commits[1], bundle=exported)
        print(json.dumps(result, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(json.dumps({"status": "failed", "stage": 5, "diagnostic": type(error).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
