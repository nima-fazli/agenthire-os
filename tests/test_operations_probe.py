import json
import threading
import time

import pytest

from app.core.probe_metrics import ProbeSample
from scripts import operations_probe as cli


def test_concurrency_is_bounded_and_all_results_are_counted(monkeypatch):
    active = peak = calls = 0
    lock = threading.Lock()
    first_pair = threading.Barrier(2, timeout=2)

    def fake(*_):
        nonlocal active, peak, calls
        with lock:
            active += 1
            peak = max(peak, active)
            calls += 1
            number = calls
        if number <= 2:
            first_pair.wait()
        time.sleep(0.001)
        with lock:
            active -= 1
        return ProbeSample(10, "ok", 200)

    monkeypatch.setattr(cli, "probe", fake)
    report = cli.measure("http://localhost:8000", requests=7, concurrency=2)
    assert calls == 7 and peak == 2 and active == 0
    assert report["passed"] == 7 and report["models_checked"] is False


@pytest.mark.parametrize("kwargs", [{"requests": 0}, {"requests": 65}, {"concurrency": 0},
                                   {"concurrency": 9}, {"timeout": float("nan")}, {"path": "/users/me"}])
def test_invalid_load_is_rejected_without_starting_threads(kwargs, monkeypatch):
    monkeypatch.setattr(cli, "probe", lambda *_: pytest.fail("Invalid input reached transport"))
    with pytest.raises(ValueError):
        cli.measure("http://localhost:8000", **kwargs)


def test_cli_distinguishes_failed_requests_latency_policy_and_invalid_input(monkeypatch, capsys):
    monkeypatch.setattr(cli, "probe", lambda *_: ProbeSample(20, "ok", 200))
    assert cli.main(["--requests", "1", "--max-p95-ms", "10"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["latency_limit_exceeded"] and report["failed"] == 0
    assert cli.main(["--base-url", "http://private-secret.invalid"]) == 2
    assert "private-secret" not in capsys.readouterr().out
    monkeypatch.setattr(cli, "probe", lambda *_: ProbeSample(1, "connection_error"))
    assert cli.main(["--requests", "1"]) == 1
    assert json.loads(capsys.readouterr().out)["failed"] == 1
