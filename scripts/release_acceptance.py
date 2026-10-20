"""Verify local release readiness; hosted release acceptance remains a separate gate."""

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scripts.backup_runtime import BackupFailure
from scripts.ci_plan import CLIENT_TESTS
from scripts.design_acceptance import verify_browser_report
from scripts.release_contract import (
    BASE,
    browser_fingerprint,
    fingerprint,
    load_manifest,
    source_snapshot,
)

PENDING = ["hosted-ci", "https-deployment", "hosted-workload", "hosted-install-migration-recovery"]
UV = ["uv", "run", "--locked", "--no-sync"]


def checks(report):
    return [
        ("source-whitespace", ["git", "diff", "--check", BASE], 60),
        ("native-ruff", UV + ["ruff", "check", "."], 120),
        ("native-python", UV + ["pytest", "-rs", "-W", "error"], 900),
        ("native-client", ["node", "--test", *CLIENT_TESTS], 120),
        ("isolated-ci-and-cleanup", UV + ["python", "-m", "scripts.ci_verify"], 10800),
        ("real-browser-design", ["node", "scripts/design_browser.mjs", "--report", str(report)], 300),
    ]


def environment(root):
    value = {k: v for k, v in os.environ.items() if not k.upper().startswith(("AGENTHIRE_", "COMPOSE_"))}
    value.update(COMPOSE_PROJECT_NAME="agenthire-os", COMPOSE_FILE=str(root / "compose.yaml"))
    if os.environ.get("AGENTHIRE_BROWSER_BINARY"):
        value["AGENTHIRE_BROWSER_BINARY"] = os.environ["AGENTHIRE_BROWSER_BINARY"]
    return value


def command(root, label, arguments, timeout, env, *, capture=False):
    print(f"[run] {label}", flush=True)
    result = subprocess.run(arguments, cwd=root, env=env, stdin=subprocess.DEVNULL,
                            capture_output=capture, text=True, encoding="utf-8", errors="replace",
                            check=False, timeout=timeout)
    if result.returncode or capture and len(result.stdout.encode("utf-8")) > 65536:
        raise RuntimeError("check_failed: " + label)
    print(f"[ok] {label}", flush=True)
    return result.stdout if capture else None


def save_report(path, report):
    path = Path(path).absolute()
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError("unsafe_release_report_path")
    data = (json.dumps(report, ensure_ascii=True, sort_keys=True, allow_nan=False, indent=2) + "\n").encode()
    if len(data) > 131072:
        raise ValueError("release_report_size_limit")
    with path.open("xb") as handle:
        path.chmod(0o600)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def configuration_digest(root):
    path = root / ".env"
    if (not path.is_file() or path.is_symlink() or path.is_junction() or path.stat().st_size > 65536):
        raise ValueError("private_environment_file_required")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_benchmark(value):
    from scripts.benchmark_run import validate_measurement

    expected = {"version", "status", "kind", "run_id", "elapsed_seconds", "diagnostic",
                "own_container_stop_requested", "resources", "measurement"}
    if (not isinstance(value, dict) or set(value) != expected or value.get("version") != "benchmark-run-v1"
            or value.get("status") != "passed" or value.get("kind") != "workflow"
            or value.get("diagnostic") is not None or value.get("own_container_stop_requested") is not False
            or type(value.get("elapsed_seconds")) not in {int, float}
            or not math.isfinite(value["elapsed_seconds"]) or not 0 <= value["elapsed_seconds"] <= 660
            or not isinstance(value.get("run_id"), str) or re.fullmatch(r"[0-9a-f]{32}", value["run_id"]) is None):
        raise ValueError("local_workload_incomplete")
    validate_measurement(value.get("measurement"), kind="workflow", run_id=value["run_id"],
                         items=4, concurrency=2, samples=3)
    resources = value.get("resources", {})
    if (not isinstance(resources, dict) or resources.get("metric") != "docker_stats_memory_usage"
            or resources.get("exact_peak") is not False or type(resources.get("samples")) is not int
            or not 2 <= resources["samples"] <= 600 or not isinstance(resources.get("services"), dict)):
        raise ValueError("local_resource_measurement_incomplete")
    for service, minimum in (("api", 1), ("postgres", 1), ("extraction-worker", 2)):
        row = resources["services"].get(service, {})
        if (not isinstance(row, dict) or type(row.get("replicas")) is not int
                or not minimum <= row["replicas"] <= 8 or type(row.get("limit_bytes")) is not int
                or row["limit_bytes"] <= 0 or type(row.get("sampled_memory_max_bytes")) is not int
                or not 0 <= row["sampled_memory_max_bytes"] <= row["limit_bytes"]
                or type(row.get("sampled_cpu_max_percent")) not in {int, float}
                or not math.isfinite(row["sampled_cpu_max_percent"]) or row["sampled_cpu_max_percent"] < 0):
            raise ValueError("local_resource_measurement_incomplete")


def refresh_workspace(root):
    from scripts.access_acceptance import database_head
    from scripts.ai_quality_acceptance import refresh_normal_workspace
    from scripts.backup_run import normal_runtime

    source = normal_runtime(root)
    if database_head(source) != "0017_access_sessions":
        raise ValueError("accepted_stage5_schema_required")
    refresh_normal_workspace(root, source)


def execute(root, directory, report, manifest, *, run=command, refresh=refresh_workspace):
    env = environment(root)
    private_configuration = configuration_digest(root)
    diagnostics = UV + ["python", "-m", "scripts.stack_diagnostics"]
    browser = directory / "browser.json"

    def step(name, args, timeout=180, *, capture=False):
        report["active_check"] = name
        started = time.monotonic()
        output = run(root, name, args, timeout, env, capture=capture)
        report["checks"].append({"name": name, "passed": True,
                                 "elapsed_seconds": round(time.monotonic() - started, 3)})
        return output

    node = step("node-version", ["node", "--version"], 30, capture=True).strip()
    if re.fullmatch(r"v24\.[0-9]+\.[0-9]+", node) is None or platform.python_version_tuple()[:2] != ("3", "12"):
        raise ValueError("python312_and_node24_required")
    report["runtime"] = {"os": platform.system(), "architecture": platform.machine(),
                         "python": platform.python_version(), "node": node}
    step("normal-stack-before", diagnostics)
    try:
        for name, args, timeout in checks(browser):
            step(name, args, timeout)
        report["active_check"] = "browser-report-integrity"
        report["browser_report"] = verify_browser_report(browser, browser_fingerprint(root))
        report["active_check"] = "normal-english-workspace"
        refresh(root)
        report["checks"].append({"name": "normal-english-workspace", "passed": True})
        raw = step("local-workload", UV + ["python", "-m", "scripts.benchmark_run", "--kind", "workflow",
                   "--execute", "--items", "4", "--concurrency", "2"], 660, capture=True)
        report["active_check"] = "workload-report-integrity"
        workload = json.loads(raw)
        validate_benchmark(workload)
        report["workload_report"] = save_report(directory / "workload.json", workload)
        template = '{"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}}}'
        engine = json.loads(step("docker-engine-capacity", ["docker", "info", "--format", template], 30, capture=True))
        if (set(engine) != {"cpus", "memory_bytes"} or type(engine["cpus"]) is not int
                or not 1 <= engine["cpus"] <= 4096 or type(engine["memory_bytes"]) is not int
                or not 0 < engine["memory_bytes"] < 2 ** 64):
            raise ValueError("docker_engine_capacity_unavailable")
        report["runtime"]["docker_engine"] = engine
    finally:
        failed = report["active_check"]
        try:
            step("normal-stack-after", diagnostics)
        except BaseException:
            report["active_check"] = "normal-stack-after"
            raise
        else:
            report["active_check"] = failed
        if configuration_digest(root) != private_configuration:
            report["active_check"] = "private-environment-stability"
            raise ValueError("private_environment_changed_during_verification")
        report["private_environment_unchanged"] = True
    report["active_check"] = "source-stability"
    if load_manifest(root) != manifest or source_snapshot(root, manifest) != report["source"]:
        raise ValueError("release_source_changed_during_verification")
    verify_browser_report(browser, browser_fingerprint(root))
    report.update(status="local_verified", active_check=None, local_verified=True)


def main(argv=None, *, root=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    directory = None
    report = {"version": "release-local-v1", "stage": 6, "scope": "local", "status": "plan",
              "executed": args.execute, "local_verified": False, "stage_complete": False,
              "external_pending": PENDING.copy(), "checks": [], "active_check": "source-preflight"}
    code = 0
    try:
        manifest = load_manifest(root)
        report["base_commit"] = BASE
        report["delivery_sha256"] = fingerprint(root, manifest["files"])
        if not args.execute:
            report.update(active_check=None, checks=["node-version", "normal-stack-before", *[n for n, _, _ in checks("BROWSER_REPORT")],
                          "normal-english-workspace", "local-workload", "docker-engine-capacity", "normal-stack-after", "source-stability"])
        else:
            report["source"] = source_snapshot(root, manifest)
            directory = root.parent / "AgentHire_OS_Release_Reports" / ("release-" + uuid4().hex)
            if any(p.is_symlink() or p.is_junction() for p in (directory, *directory.parents)):
                raise ValueError("unsafe_release_report_directory")
            directory.mkdir(parents=True, mode=0o700)
            report["started_at"] = datetime.now(UTC).isoformat()
            execute(root, directory, report, manifest)
    except KeyboardInterrupt:
        report.update(status="interrupted", diagnostic="KeyboardInterrupt")
        code = 130
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError, BackupFailure) as error:
        report.update(status="failed", diagnostic=type(error).__name__)
        code = 2
    if directory is not None and directory.is_dir():
        report["finished_at"] = datetime.now(UTC).isoformat()
        try:
            report["saved_report"] = save_report(directory / "release.json", report)
        except (OSError, ValueError, TypeError):
            report.update(status="failed", local_verified=False, diagnostic="release_report_write_failed")
            code = code or 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
