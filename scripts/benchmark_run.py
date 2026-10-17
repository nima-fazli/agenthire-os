"""Host supervisor for a fixed synthetic workload/model command plus sampled resources."""

import argparse
import asyncio
import json
import math
import re
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from app.core.benchmark_metrics import PHASES
from app.core.resource_metrics import ResourceSummary
from scripts.ci_plan import repository_root
from scripts.resource_watch import inventory, snapshot


async def bounded_read(stream, limit):
    value = bytearray()
    while part := await stream.read(4096):
        value.extend(part)
        if len(value) > limit:
            raise ValueError("Benchmark output limit exceeded.")
    return bytes(value)


def benchmark_command(kind, name, *, items=4, concurrency=2, samples=3):
    if kind not in {"workflow", "models"} or not re.fullmatch(r"agenthire-bench-[0-9a-f]{32}", name):
        raise ValueError("Invalid benchmark command.")
    if (type(items) is not int or not 1 <= items <= 8 or type(concurrency) is not int or not 1 <= concurrency <= 4 or
            type(samples) is not int or not 1 <= samples <= 4):
        raise ValueError("Invalid benchmark bounds.")
    command = ["docker", "compose", "--profile", "smoke", "run", "--rm", "--no-deps", "--name", name,
               "smoke", "python", "-m"]
    if kind == "workflow":
        command += ["scripts.workload_benchmark", "--execute", "--items", str(items), "--concurrency", str(concurrency),
                    "--run-id", name.removeprefix("agenthire-bench-")]
    else:
        command += ["scripts.model_benchmark", "--execute", "--samples", str(samples)]
    return command


def valid_distribution(value, count=None, *, failures=False):
    keys = {"samples", "p50_ms", "p95_ms", "max_ms"} | ({"failed"} if failures else set())
    if not isinstance(value, dict) or set(value) != keys or type(value["samples"]) is not int or not 1 <= value["samples"] <= 4096:
        return False
    if count is not None and value["samples"] != count:
        return False
    if failures and (type(value["failed"]) is not int or value["failed"] != 0):
        return False
    times = [value[key] for key in ("p50_ms", "p95_ms", "max_ms")]
    return all(type(v) in {int, float} and math.isfinite(v) and v >= 0 for v in times) and times == sorted(times)


def validate_measurement(value, *, kind, run_id, items, samples, concurrency=2):
    if not isinstance(value, dict) or value.get("status") != "passed":
        raise ValueError("Benchmark did not pass.")
    if kind == "workflow":
        keys = {"version", "status", "run_id", "corpus_kind", "source_kind", "items", "concurrency", "completed",
                "queued_observed", "running_observed", "cleanup", "diagnostic", "models_checked", "phases"}
        valid = set(value) == keys and value["version"] == "workload-benchmark-v1" and value["run_id"] == run_id
        valid = valid and value["corpus_kind"] == "synthetic_pdf" and value["source_kind"] == "http_real_worker"
        valid = valid and type(value["items"]) is int and value["items"] == items and value["completed"] == items
        valid = valid and type(value["concurrency"]) is int and value["concurrency"] == min(items, concurrency)
        valid = valid and value["cleanup"] == "completed" and value["diagnostic"] is None and value["models_checked"] is False
        valid = valid and all(type(value[key]) is int and 0 <= value[key] <= items for key in ("completed", "queued_observed", "running_observed"))
        phases = value.get("phases")
        valid = valid and isinstance(phases, dict) and {"workflow", "request_to_completion", "retrieval"}.issubset(phases)
        valid = valid and not set(phases) - PHASES and all(valid_distribution(v, failures=True) for v in phases.values())
        valid = valid and phases["workflow"]["samples"] == items and phases["request_to_completion"]["samples"] == items
    else:
        keys = {"version", "status", "source_kind", "models_checked", "concurrency", "cpu_only", "cold_warm_controlled", "embedding", "chat"}
        valid = set(value) == keys and value["version"] == "model-benchmark-v1" and value["models_checked"] is True
        valid = valid and value["source_kind"] == "synthetic_client_live_transport" and value["cpu_only"] is True
        valid = valid and type(value["concurrency"]) is int and value["concurrency"] == 1 and value["cold_warm_controlled"] is False
        for label, tag in (("embedding", "qwen3-embedding:0.6b"), ("chat", "qwen3:0.6b")):
            part = value.get(label)
            required = {"model", "digest", "latency", "first_ms"} | ({"dimensions"} if label == "embedding" else {"grounding_checked", "input_tokens", "output_tokens"})
            valid = valid and isinstance(part, dict) and set(part) == required and part["model"] == tag
            valid = valid and isinstance(part["digest"], str) and re.fullmatch(r"[0-9a-f]{64}", part["digest"]) is not None
            valid = valid and valid_distribution(part["latency"], samples) and type(part["first_ms"]) in {int, float}
            valid = valid and math.isfinite(part["first_ms"]) and 0 <= part["first_ms"] <= part["latency"]["max_ms"] + .001
            if label == "embedding":
                valid = valid and part["dimensions"] == 1024
            else:
                valid = valid and part["grounding_checked"] is True and all(type(part[k]) is int and part[k] > 0 for k in ("input_tokens", "output_tokens"))
    if not valid:
        raise ValueError("Invalid benchmark report.")


async def supervise(root, *, kind, items=4, concurrency=2, samples=3, deadline=600):
    root = repository_root(root)
    if type(deadline) is not int or not 30 <= deadline <= 600:
        raise ValueError("Invalid benchmark deadline.")
    name = "agenthire-bench-" + uuid4().hex
    command = benchmark_command(kind, name, items=items, concurrency=concurrency, samples=samples)
    containers = await asyncio.to_thread(inventory, root)
    if kind == "workflow" and (sum(value == "extraction-worker" for value in containers.values()) < 2 or
                               not {"api", "postgres"}.issubset(containers.values())):
        raise ValueError("Workload services unavailable.")
    if kind == "models" and "ollama" not in containers.values():
        raise ValueError("Ollama unavailable.")
    summary = ResourceSummary()
    summary.add(await asyncio.to_thread(snapshot, containers))
    child = await asyncio.create_subprocess_exec(*command, cwd=root, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout = asyncio.create_task(bounded_read(child.stdout, 262144))
    stderr = asyncio.create_task(bounded_read(child.stderr, 65536))
    waited = asyncio.create_task(child.wait())
    started, stop_requested, failure = time.monotonic(), False, None
    output = None
    try:
        async with asyncio.timeout(deadline):
            while not waited.done():
                for task in (stdout, stderr):
                    if task.done():
                        task.result()
                summary.add(await asyncio.to_thread(snapshot, containers))
                if not waited.done():
                    await asyncio.sleep(1)
            await asyncio.gather(stdout, stderr, waited)
            output = json.loads(stdout.result())
            if child.returncode:
                raise ValueError("Benchmark did not pass.")
            validate_measurement(output, kind=kind, run_id=name.removeprefix("agenthire-bench-"), items=items,
                                 samples=samples, concurrency=concurrency)
            summary.add(await asyncio.to_thread(snapshot, containers))
    except asyncio.CancelledError:
        failure = "interrupted"
    except (OSError, ValueError, TypeError, TimeoutError, subprocess.SubprocessError):
        failure = "benchmark_incomplete"
    finally:
        if child.returncode is None:
            stop_requested = True
            try:
                await asyncio.to_thread(subprocess.run, ("docker", "stop", "--time", "5", name),
                                        capture_output=True, timeout=15, check=False, stdin=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                pass
            if child.returncode is None:
                child.terminate()
            try:
                await asyncio.wait_for(child.wait(), 5)
            except TimeoutError:
                child.kill()
                await child.wait()
        for task in (stdout, stderr, waited):
            if not task.done():
                task.cancel()
        await asyncio.gather(stdout, stderr, waited, return_exceptions=True)
    return {"version": "benchmark-run-v1", "status": "passed" if failure is None else "incomplete",
            "kind": kind, "run_id": name.removeprefix("agenthire-bench-"),
            "elapsed_seconds": round(time.monotonic() - started, 3), "diagnostic": failure,
            "own_container_stop_requested": stop_requested, "resources": summary.report(),
            "measurement": output if failure is None else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("workflow", "models"), required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--items", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--samples", type=int, choices=range(1, 5), default=3)
    parser.add_argument("--deadline", type=int, choices=range(30, 601), default=600)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"status": "plan", "kind": args.kind, "execution_requires": "--execute"}))
        return 0
    try:
        report = asyncio.run(supervise(Path.cwd(), kind=args.kind, items=args.items, concurrency=args.concurrency,
                                      samples=args.samples, deadline=args.deadline))
        code = 130 if report.get("diagnostic") == "interrupted" else (0 if report["status"] == "passed" else 1)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError):
        report, code = {"status": "unavailable", "diagnostic": "benchmark_unavailable"}, 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
