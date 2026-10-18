"""Exercise retained capture/restore using only a fresh synthetic source."""

import argparse
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

from app.core.backup_store import BackupStore
from scripts.backup_run import BASELINE, capture, restore
from scripts.backup_runtime import BackupFailure, Runtime
from scripts.ci_plan import (
    cleanup_step,
    compose_prefix,
    new_project_name,
    repository_root,
)
from scripts.ci_verify import isolated_environment, preflight, write_environment


def execute(root, *, runner=subprocess.run, report=None):
    if report is None:
        report = {}
    report.update(status="failed", scope="synthetic_retained_backup_gate", normal_stack_touched=False,
                  models_checked=False, source_cleanup="not_started", retained_after_gate=False, owned_projects=[])
    with tempfile.TemporaryDirectory(prefix="agenthire-backup-gate-", dir=root.parent) as temporary:
        directory = Path(temporary).resolve()
        store = BackupStore(directory / "store", root)
        store.initialize()
        project = new_project_name()
        env_file = directory / "source.env"
        environment = isolated_environment(os.environ, project, env_file)
        preflight(project, root=root, environment=environment, runner=runner)
        write_environment(env_file, environment)
        source = Runtime(root, project, compose_prefix(root, project, env_file), environment, runner=runner)
        report["owned_projects"].append(project)
        try:
            source.call(("--profile", "smoke", "build", "api", "migrate", "extraction-worker", "smoke"), timeout=1200)
            source.call(("up", "--detach", "--no-build", "--wait", "--wait-timeout", "180",
                         "--scale", "extraction-worker=2", "api", "extraction-worker"), timeout=360)
            source.call(("--profile", "smoke", "run", "--rm", "--no-deps", "-T", "--env",
                         "AGENTHIRE_RECOVERY_PROJECT=" + project, "smoke", "python", "-m",
                         "scripts.recovery_fixture", "seed", "--project", project, "--run-id", project[-32:]))
            with store.locked():
                captured = {}
                try:
                    identity = capture(store, source, env_file, BASELINE, "synthetic", captured)
                finally:
                    report["source_resume"] = captured.get("source_resume", "not_needed")
                if captured.get("source_resume") != "completed":
                    raise BackupFailure("synthetic_source_resume_failed")
                recovered = {}
                try:
                    restore(store, identity, root, recovered, runner=runner, fixture_seed=project[-32:])
                finally:
                    if recovered.get("owned_project"):
                        report["owned_projects"].append(recovered["owned_project"])
                    report["isolated_restore_cleanup"] = recovered.get("cleanup", "not_acquired")
                if recovered.get("cleanup") != "completed" or not recovered.get("restore_receipt_created"):
                    raise BackupFailure("synthetic_retained_restore_failed")
                store.prune(3)
                report.update(status="passed", source_resume="completed", retained_bundle_verified=True,
                              database_integrity_verified=True, document_integrity_verified=True,
                              restore_receipt_created=True, isolated_restore_cleanup="completed")
        finally:
            step = cleanup_step(source.prefix)
            report["source_cleanup"] = "attention"
            source.raw(step.command, timeout=step.timeout)
            report["source_cleanup"] = "completed"
    return report


def main(argv=None, *, runner=subprocess.run):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    report = {"status": "failed", "normal_stack_touched": False}
    try:
        root = repository_root(Path.cwd())
        if not args.execute:
            print(json.dumps({"status": "plan", "requires": "--execute", "normal_stack_touched": False}))
            return 0
        execute(root, runner=runner, report=report)
    except KeyboardInterrupt:
        report.update(status="interrupted", diagnostic="operation_interrupted")
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, zipfile.BadZipFile,
            subprocess.SubprocessError, BackupFailure):
        report.update(status="failed", diagnostic="backup_gate_unavailable")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] in {"passed", "plan"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
