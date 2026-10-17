"""Host-only bounded Compose/Docker resource sampling; outputs service aggregates."""

import argparse
import json
import math
import subprocess
import time
from pathlib import Path

from app.core.resource_metrics import SERVICES, ResourceSummary
from scripts.ci_plan import repository_root
from scripts.stack_diagnostics import parse_inventory


def command_output(command, *, runner=subprocess.run):
    result = runner(command, capture_output=True, text=True, timeout=5,
                    check=False, stdin=subprocess.DEVNULL)
    if result.returncode or len(result.stdout) > 65536:
        raise ValueError("Resource command unavailable.")
    return result.stdout


def inventory(root, *, runner=subprocess.run):
    root = repository_root(root)
    rows = parse_inventory(command_output(("docker", "compose", "--file", str(root / "compose.yaml"),
                                          "--profile", "semantic", "ps", "--all", "--format", "json"), runner=runner))
    result = {row["ID"]: row["Service"] for row in rows if row["Service"] in SERVICES and row.get("State") == "running"}
    if not 1 <= len(result) <= 16:
        raise ValueError("Resource inventory unavailable.")
    return result


def snapshot(containers, *, runner=subprocess.run):
    if not containers or len(containers) > 16:
        raise ValueError("Invalid resource inventory.")
    import re

    if any(not re.fullmatch(r"[0-9a-f]{12,64}", key) or value not in SERVICES for key, value in containers.items()):
        raise ValueError("Invalid resource inventory.")
    text = command_output(("docker", "stats", "--no-stream", "--format", "{{json .}}", *containers), runner=runner)
    result, seen = {}, set()
    for line in text.splitlines():
        row = json.loads(line)
        identity = row.get("ID") if isinstance(row, dict) else None
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{12,64}", identity):
            raise ValueError("Invalid resource identity.")
        matches = [key for key in containers if key.startswith(identity) or identity.startswith(key)]
        if len(matches) != 1 or matches[0] in seen:
            raise ValueError("Resource topology changed.")
        key = matches[0]
        seen.add(key)
        result.setdefault(containers[key], []).append({"CPUPerc": row.get("CPUPerc"), "MemUsage": row.get("MemUsage")})
    if seen != set(containers):
        raise ValueError("Resource sample incomplete.")
    return result


def watch(root, *, samples=15, interval=1, runner=subprocess.run, sleeper=time.sleep):
    if type(samples) is not int or not 1 <= samples <= 120 or type(interval) not in {int, float} or not math.isfinite(interval) or not .25 <= interval <= 5:
        raise ValueError("Invalid resource sampling bounds.")
    containers = inventory(root, runner=runner)
    summary = ResourceSummary()
    started = time.monotonic()
    for index in range(samples):
        if index:
            sleeper(interval)
        summary.add(snapshot(containers, runner=runner))
    return {"status": "captured", "elapsed_seconds": round(time.monotonic() - started, 3),
            "model_inference": False, **summary.report()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, choices=range(1, 121), default=15)
    parser.add_argument("--interval", type=float, default=1)
    args = parser.parse_args(argv)
    try:
        report, code = watch(Path.cwd(), samples=args.samples, interval=args.interval), 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        report, code = {"status": "unavailable", "diagnostic": "resource_sampling_unavailable"}, 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
