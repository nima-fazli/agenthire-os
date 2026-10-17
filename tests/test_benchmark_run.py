import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from scripts import benchmark_run as cli

RUN = "a" * 32


def workload_report():
    stat = {"samples": 4, "p50_ms": 1, "p95_ms": 2, "max_ms": 2, "failed": 0}
    return {"version": "workload-benchmark-v1", "status": "passed", "run_id": RUN,
            "corpus_kind": "synthetic_pdf", "source_kind": "http_real_worker", "items": 4, "concurrency": 2,
            "completed": 4, "queued_observed": 4, "running_observed": 1, "cleanup": "completed", "diagnostic": None,
            "models_checked": False, "phases": {name: dict(stat) for name in ("workflow", "request_to_completion", "retrieval")}}


def test_only_fixed_local_benchmark_commands_and_generated_container_names_are_accepted():
    command = cli.benchmark_command("workflow", "agenthire-bench-" + RUN)
    assert "--no-deps" in command and command[-2:] == ["--run-id", RUN]
    assert "--execute" in command and command[command.index("--name") + 1] == "agenthire-bench-" + RUN
    with pytest.raises(ValueError): cli.benchmark_command("shell", "agenthire-bench-" + RUN)
    with pytest.raises(ValueError): cli.benchmark_command("models", "api")


@pytest.mark.parametrize("change", ["private-field", "cleanup", "partial", "negative", "wrong-kind"], ids=str)
def test_supervisor_rejects_private_or_incomplete_success_claims(change):
    report = copy.deepcopy(workload_report())
    if change == "private-field": report["token"] = "private"
    elif change == "cleanup": report["cleanup"] = "manual_review_required"
    elif change == "partial": report["completed"] = 3
    elif change == "negative": report["phases"]["workflow"]["max_ms"] = -1
    else: report["source_kind"] = "fixture"
    with pytest.raises(ValueError):
        cli.validate_measurement(report, kind="workflow", run_id=RUN, items=4, samples=3)


def test_valid_measurement_is_accepted():
    cli.validate_measurement(workload_report(), kind="workflow", run_id=RUN, items=4, samples=3)


def test_successful_supervisor_keeps_measurement_and_complete_resource_samples(monkeypatch, tmp_path):
    async def check():
        containers = {"a" * 64: "api", "b" * 64: "postgres",
                      "c" * 64: "extraction-worker", "d" * 64: "extraction-worker"}
        monkeypatch.setattr(cli, "repository_root", lambda root: root)
        monkeypatch.setattr(cli, "inventory", lambda root: containers)
        monkeypatch.setattr(cli, "snapshot", lambda mapping: {
            name: [{"CPUPerc": "1%", "MemUsage": "1MiB / 768MiB"}] * list(mapping.values()).count(name)
            for name in set(mapping.values())})
        async def spawn(*command, **options):
            report = workload_report() | {"run_id": command[command.index("--run-id") + 1]}
            stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()
            stdout.feed_data(json.dumps(report).encode())
            stdout.feed_eof()
            stderr.feed_eof()
            async def wait(): return 0
            return SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr, wait=wait)
        monkeypatch.setattr(cli.asyncio, "create_subprocess_exec", spawn)
        def stop(*args, **kwargs): pytest.fail("Successful container must not be stopped.")
        monkeypatch.setattr(cli.subprocess, "run", stop)
        result = await cli.supervise(tmp_path, kind="workflow")
        assert result["status"] == "passed" and result["measurement"]["run_id"] == result["run_id"]
        assert result["resources"]["samples"] >= 2 and not result["own_container_stop_requested"]
        assert result["resources"]["services"]["extraction-worker"]["replicas"] == 2
    asyncio.run(check())


def test_output_reader_rejects_overflow_without_returning_the_body():
    async def check():
        reader = asyncio.StreamReader()
        reader.feed_data(b"private" * 100)
        reader.feed_eof()
        with pytest.raises(ValueError, match="limit"):
            await cli.bounded_read(reader, 100)
    asyncio.run(check())


def test_after_child_start_resource_failure_stops_only_owned_container(monkeypatch, tmp_path):
    async def check():
        class Child:
            returncode = None
            def __init__(self):
                self.done = asyncio.Event()
                self.stdout, self.stderr = asyncio.StreamReader(), asyncio.StreamReader()
            async def wait(self):
                await self.done.wait()
                return self.returncode
            def terminate(self):
                self.returncode = -15
                self.stdout.feed_eof()
                self.stderr.feed_eof()
                self.done.set()
            def kill(self): self.terminate()
        child, stops, calls = Child(), [], 0
        monkeypatch.setattr(cli, "repository_root", lambda root: root)
        monkeypatch.setattr(cli, "inventory", lambda root: {"a" * 64: "ollama"})
        def snapshot(containers):
            nonlocal calls
            calls += 1
            if calls > 1: raise ValueError("private-output")
            return {"ollama": [{"CPUPerc": "0%", "MemUsage": "1MiB / 3GiB"}]}
        monkeypatch.setattr(cli, "snapshot", snapshot)
        async def spawn(*args, **kwargs): return child
        monkeypatch.setattr(cli.asyncio, "create_subprocess_exec", spawn)
        def stop(command, **kwargs):
            stops.append(command)
            return SimpleNamespace(returncode=0)
        monkeypatch.setattr(cli.subprocess, "run", stop)
        result = await cli.supervise(tmp_path, kind="models")
        assert result["status"] == "incomplete" and result["measurement"] is None
        assert len(stops) == 1 and stops[0][:4] == ("docker", "stop", "--time", "5")
        assert stops[0][-1] == "agenthire-bench-" + result["run_id"]
        assert "private" not in json.dumps(result)
    asyncio.run(check())
