import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import ai_quality_run as module
from scripts.ai_quality_contract import load_reference
from tests.test_ai_quality_metrics import report


@pytest.mark.parametrize("failure", [None, "setup", "threshold", "timeout", "cancel", "cleanup"])
def test_owned_cleanup_and_failed_measurement_retention(monkeypatch, tmp_path, failure):
    calls = []
    measurement = report(kind="fixture" if failure == "threshold" else "live")

    async def command(args, root, environment, timeout):
        calls.append(args)
        if "down" in args:
            return (1 if failure == "cleanup" else 0), b""
        if failure == "setup":
            return 1, b""
        if failure == "timeout":
            raise TimeoutError
        if failure == "cancel":
            raise asyncio.CancelledError
        return (1 if failure == "threshold" else 0, json.dumps(measurement).encode()) if "scripts.ai_quality_smoke" in args else (0, b"")

    monkeypatch.setattr(module, "command", command)
    monkeypatch.setattr(module, "preflight", lambda *args, **kwargs: None)
    result = asyncio.run(module.execute(tmp_path, "agenthire-ci-" + "a" * 32, tmp_path / "quality.env", {}))
    assert "down" in calls[-1] and "--volumes" in calls[-1]
    assert result["status"] == ("passed" if failure is None else "failed")
    assert result["cleanup"] == ("attention_required" if failure == "cleanup" else "completed")
    if failure == "threshold":
        assert result["measurement"] == measurement and result["diagnostic"] == "quality_gate_failed"
    if failure == "cancel":
        assert result["diagnostic"] == "interrupted"


def test_default_is_plan_and_preflight_collision_never_cleans(monkeypatch, capsys):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(root)
    monkeypatch.setattr(module, "preflight", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("occupied")))
    monkeypatch.setattr(module, "execute", lambda *args, **kwargs: pytest.fail("must not execute"))
    assert module.main([]) == 0
    assert json.loads(capsys.readouterr().out)["models_checked"] is False
    assert module.main(["--execute"]) == 2


def test_private_reports_are_unique_and_hash_checked(tmp_path):
    value = {"safe": "aggregate"}
    first = module.save_report(tmp_path, value)
    second = module.save_report(tmp_path, value)
    assert first["path"] != second["path"] and first["sha256"] == second["sha256"]
    assert json.loads(Path(first["path"]).read_bytes()) == value
    assert load_reference().version == "ai-quality-reference-v1"


def test_subprocess_drains_large_model_download_progress_without_leaking_it(tmp_path):
    script = "import sys; sys.stderr.write('x'*200000); print('not a report')"
    code, output = asyncio.run(module.command((sys.executable, "-c", script), tmp_path, None, 10))
    assert code == 0 and output == b""


def test_collection_output_is_retained_but_size_bounded(tmp_path):
    args = (sys.executable, "-c", "print('{}')", "scripts.ai_quality_smoke")
    code, output = asyncio.run(module.command(args, tmp_path, None, 10))
    assert code == 0 and output.splitlines() == [b"{}"]
    args = (sys.executable, "-c", "print('x'*2200000)", "scripts.ai_quality_smoke")
    with pytest.raises(ValueError):
        asyncio.run(module.command(args, tmp_path, None, 10))


def test_cleanup_inventory_timeout_is_retained_as_a_failed_report(monkeypatch, tmp_path):
    async def command(args, *unused):
        return (0, json.dumps(report()).encode()) if "scripts.ai_quality_smoke" in args else (0, b"")

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired("docker", 30)

    monkeypatch.setattr(module, "command", command)
    monkeypatch.setattr(module, "preflight", timed_out)
    value = asyncio.run(module.execute(tmp_path, "agenthire-ci-" + "a" * 32, tmp_path / "quality.env", {}))
    assert value["status"] == "failed" and value["cleanup"] == "attention_required"
    assert value["measurement"]["quality_passed"]


def test_plan_pins_tags_and_uses_only_namespaced_compose_overrides(tmp_path):
    prefix, steps = module.plan(tmp_path, "agenthire-ci-" + "a" * 32, tmp_path / "quality.env")
    assert str(tmp_path / "compose.ci.yaml") in prefix and str(tmp_path / "compose.quality.yaml") in prefix
    args = [part for _, command, _ in steps for part in command]
    assert "qwen3-embedding:0.6b" in args and "qwen3:0.6b" in args
    assert not {"--publish", "--service-ports", "extraction-worker", "embedding-worker"} & set(args)
