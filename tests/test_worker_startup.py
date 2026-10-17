"""Fresh-process checks distinguish heartbeat probes from worker startup."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BLOCKER = """
import runpy
import socket
import sys

class RejectRuntime:
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise RuntimeError("Probe imported worker runtime.")
        return None

def reject_network(*args, **kwargs):
    raise RuntimeError("Probe attempted network access.")

socket.create_connection = reject_network
socket.socket.connect = reject_network
sys.meta_path.insert(0, RejectRuntime())
"""
RUNTIME = (
    "sqlalchemy", "asyncpg", "app.db", "app.services", "app.repositories",
    "app.models", "app.core.semantic_embeddings", "app.core.local_embeddings",
    "app.core.local_chat", "app.core.pdf_extraction", "app.core.document_storage",
)


def execute(tmp_path, source, **values):
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith("AGENTHIRE_")}
    environment.update({"PYTHONPATH": str(ROOT), "TMPDIR": str(tmp_path),
                        "TMP": str(tmp_path), "TEMP": str(tmp_path),
                        "AGENTHIRE_ENVIRONMENT": "test"})
    environment.update(values)
    return subprocess.run([sys.executable, "-c", source], cwd=tmp_path,
                          env=environment, capture_output=True, text=True, check=False, timeout=15)


def test_settings_construct_without_database_or_model_runtime(tmp_path):
    source = "blocked = " + repr(RUNTIME) + "\n" + BLOCKER + """
from app.core.config import get_settings
settings = get_settings()
assert settings.extraction_timeout_seconds == 120
assert settings.embedding_base_url == "http://ollama:11434"
"""
    result = execute(tmp_path, source, AGENTHIRE_EXTRACTION_TIMEOUT_SECONDS="120",
                     AGENTHIRE_EXTRACTION_LEASE_SECONDS="150",
                     AGENTHIRE_EMBEDDING_BASE_URL="http://ollama:11434/")
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize("mode", ["extraction", "embedding"])
@pytest.mark.parametrize("case", ["fresh", "missing", "stale", "future", "malformed", "nonfinite"], ids=str)
def test_health_cli_checks_heartbeat_without_worker_runtime(tmp_path, mode, case):
    age = {"fresh": 5, "stale": 180, "future": -60}.get(case, 0)
    value = {"malformed": "invalid", "nonfinite": "nan"}.get(case, str(time.monotonic() - age))
    if case != "missing":
        (tmp_path / ("agenthire-" + mode + ".heartbeat")).write_text(value, encoding="ascii")
    blocked = RUNTIME + (("app.core", "asyncio", "logging") if mode == "embedding" else ())
    module = "app.workers.document_" + ("extraction" if mode == "extraction" else "embeddings")
    source = "blocked = " + repr(blocked) + "\n" + BLOCKER
    source += f"\nsys.argv = [{module!r}, '--healthcheck']\nrunpy.run_module({module!r}, run_name='__main__')\n"
    result = execute(tmp_path, source)
    assert result.returncode == (0 if case == "fresh" else 1), result.stderr
    assert result.stdout == result.stderr == ""


def test_extraction_health_cli_retains_configured_long_task_margin(tmp_path):
    (tmp_path / "agenthire-extraction.heartbeat").write_text(str(time.monotonic() - 120), encoding="ascii")
    source = "blocked = " + repr(RUNTIME) + "\n" + BLOCKER + """
sys.argv = ["app.workers.document_extraction", "--healthcheck"]
runpy.run_module("app.workers.document_extraction", run_name="__main__")
"""
    result = execute(tmp_path, source, AGENTHIRE_EXTRACTION_TIMEOUT_SECONDS="120",
                     AGENTHIRE_EXTRACTION_LEASE_SECONDS="150")
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize("mode", ["extraction", "embedding"])
def test_normal_cli_still_requests_worker_runtime(tmp_path, mode):
    module = "app.workers.document_" + ("extraction" if mode == "extraction" else "embeddings")
    source = """
import runpy
import sys

class RuntimeRequested(Exception):
    pass

class DetectRuntime:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"app.core.document_storage", "app.core.local_embeddings"}:
            raise RuntimeRequested
        return None

sys.meta_path.insert(0, DetectRuntime())
"""
    source += f"\nsys.argv = [{module!r}]\n"
    source += f"try:\n    runpy.run_module({module!r}, run_name='__main__')\nexcept RuntimeRequested:\n    raise SystemExit(0)\nraise SystemExit(9)\n"
    result = execute(tmp_path, source, AGENTHIRE_SEMANTIC_ENABLED="true")
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""
