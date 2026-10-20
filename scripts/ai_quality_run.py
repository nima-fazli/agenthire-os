"""Plan or run isolated live model evaluation; clean up only this run's owned resources."""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.core.grounded_explanations import strict_json
from scripts.ai_quality_contract import load_reference
from scripts.ai_quality_metrics import validate_report
from scripts.benchmark_run import bounded_read
from scripts.ci_plan import compose_prefix, new_project_name, repository_root
from scripts.ci_verify import isolated_environment, preflight, write_environment

MAX_REPORT_BYTES = 2 * 1024 * 1024


def plan(root, project, env_file):
    prefix = compose_prefix(root, project, env_file) + ("--file", str(root / "compose.quality.yaml"),
                                                      "--profile", "semantic", "--profile", "smoke")
    return prefix, (
        ("quality-config", ("config", "--quiet"), 30),
        ("quality-images", ("build", "api", "migrate", "smoke"), 1200),
        ("quality-model-service", ("up", "-d", "--no-build", "--wait", "--wait-timeout", "180", "postgres", "ollama"), 240),
        ("quality-embedding-download", ("exec", "-T", "ollama", "ollama", "pull", "qwen3-embedding:0.6b"), 900),
        ("quality-chat-download", ("exec", "-T", "ollama", "ollama", "pull", "qwen3:0.6b"), 900),
        ("quality-api", ("up", "-d", "--no-build", "--wait", "--wait-timeout", "180", "api"), 240),
        ("quality-live-collection", ("run", "--rm", "--no-deps", "-T", "--name", project + "-quality",
                                     "smoke", "python", "-m", "scripts.ai_quality_smoke", "--live-model"), 1800),
    )


async def command(arguments, root, environment, timeout):
    """Bound process lifetime and captured output while draining both output streams."""
    child = await asyncio.create_subprocess_exec(*arguments, cwd=root, env=environment,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    async def drain(stream):
        while await stream.read(8192):
            pass
        return b""

    capture = "scripts.ai_quality_smoke" in arguments
    tasks = [asyncio.create_task(bounded_read(child.stdout, MAX_REPORT_BYTES) if capture else drain(child.stdout)),
             asyncio.create_task(drain(child.stderr)), asyncio.create_task(child.wait())]
    try:
        async with asyncio.timeout(timeout):
            out, _, code = await asyncio.gather(*tasks)
        return code, out
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def execute(root, project, env_file, environment, *, deadline=3600):
    if type(deadline) is not int or not 300 <= deadline <= 7200:
        raise ValueError("invalid_quality_deadline")
    prefix, steps = plan(root, project, env_file)
    started = time.monotonic()
    report = {"version": "ai-quality-run-v1", "project": project, "started_at": datetime.now(UTC).isoformat(),
              "status": "failed", "cleanup": "pending", "diagnostic": None, "measurement": None, "checks": []}
    try:
        for name, arguments, timeout in steps:
            print("[run] " + name, flush=True)
            remaining = deadline - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError
            code, output = await command(prefix + arguments, root, environment, min(timeout, remaining))
            report["checks"].append({"name": name, "exit": code})
            if name == "quality-live-collection":
                value = strict_json(output)
                validate_report(load_reference(), value, require_contract=False)
                report["measurement"] = value
                if code or not value["quality_passed"]:
                    report["diagnostic"] = "quality_gate_failed"
                    break
            elif code:
                report["diagnostic"] = "quality_setup_failed"
                break
        else:
            report["status"] = "passed"
    except asyncio.CancelledError:
        report["diagnostic"] = "interrupted"
    except (OSError, ValueError, TypeError, KeyError, TimeoutError, subprocess.SubprocessError):
        report["diagnostic"] = "quality_run_incomplete"
    finally:
        # The caller completed preflight before execute acquired any resources.
        try:
            code, _ = await command(prefix + ("down", "--volumes", "--remove-orphans"), root, environment, 240)
            report["cleanup"] = "completed" if code == 0 else "attention_required"
            if code == 0:
                await asyncio.to_thread(preflight, project, root=root, environment=environment)
        except (OSError, ValueError, TimeoutError, subprocess.SubprocessError, asyncio.CancelledError):
            report["cleanup"] = "attention_required"
        if report["cleanup"] != "completed":
            report["status"] = "failed"
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return report


def save_report(directory, report):
    directory = Path(directory).absolute()
    if any(p.is_symlink() or p.is_junction() for p in (directory, *directory.parents)):
        raise ValueError("unsafe_quality_report_directory")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("quality-" + uuid4().hex + ".json")
    data = (json.dumps(report, ensure_ascii=True, sort_keys=True, allow_nan=False, indent=2) + "\n").encode()
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("quality_report_too_large")
    with path.open("xb") as handle:
        path.chmod(0o600)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--deadline", type=int, default=3600)
    args = parser.parse_args(argv)
    try:
        root = repository_root(Path.cwd())
        if not (root / "compose.quality.yaml").is_file() or not 300 <= args.deadline <= 7200:
            raise ValueError("invalid_quality_checkout_or_deadline")
        project = new_project_name()
        if not args.execute:
            _, steps = plan(root, project, root / "QUALITY_ENV_CREATED_AT_RUNTIME")
            print(json.dumps({"status": "plan", "checks": [name for name, _, _ in steps], "models_checked": False,
                              "deadline_seconds": args.deadline, "execution_requires": "--execute"}))
            return 0
        with tempfile.TemporaryDirectory(prefix="agenthire-quality-") as directory:
            env_file = Path(directory).resolve() / "quality.env"
            environment = isolated_environment(os.environ, project, env_file)
            preflight(project, root=root, environment=environment)
            write_environment(env_file, environment)
            report = asyncio.run(execute(root, project, env_file, environment, deadline=args.deadline))
        saved = save_report(root.parent / "AgentHire_OS_Quality_Reports", report)
        print(json.dumps({"status": report["status"], "cleanup": report["cleanup"], "report": saved}, sort_keys=True))
        return 0 if report["status"] == "passed" else 1
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print(json.dumps({"status": "failed", "diagnostic": "quality_setup_or_save_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
