import asyncio
import json
from threading import Lock
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.core.benchmark_metrics import Measurements
from scripts import workload_benchmark as cli
from scripts.benchmark_http import BenchmarkFailure


class API:
    def __init__(self, metrics, *, extraction="succeeded", bad_scope=False):
        self.metrics, self.extraction, self.bad_scope = metrics, extraction, bad_scope
        self.calls, self.candidates, self.documents = [], [], {}
        self.org = str(uuid4())
        self.lock = Lock()

    def call(self, method, path, *, phase, expected=200, payload=None, **options):
        self.metrics.add(phase, 1)
        with self.lock:
            self.calls.append((method, path))
            if path == "/users/register":
                return {"id": str(uuid4()), "email": payload["email"]}
            if path == "/auth/login":
                return {"access_token": "private.jwt.token"}
            if path == "/organizations":
                return {"id": self.org, "slug": payload["slug"]}
            if path.endswith("/jobs"):
                self.job = str(uuid4())
                return {"id": self.job, "organization_id": self.org}
            if path.endswith("/search-profile"):
                return {"revision": 1}
            if path.endswith("/candidates"):
                candidate = str(uuid4())
                self.candidates.append(candidate)
                return {"id": candidate, "organization_id": str(uuid4()) if self.bad_scope else self.org}
            if path.endswith("/applications"):
                return {"id": str(uuid4()), "organization_id": self.org, "status": "applied", **payload}
            if path.endswith("/transitions"):
                return {"status": "screening"}
            if "?filename=" in path:
                candidate = path.split("/candidates/")[1].split("/")[0]
                document = str(uuid4())
                self.documents[candidate] = document
                return {"id": document, "candidate_id": candidate, "organization_id": self.org}
            if path.endswith("/extraction"):
                return {"status": "queued" if method == "POST" else self.extraction}
            if path.endswith("/chunks"):
                return {"chunk_count": 1}
            if "/candidate-retrieval?" in path:
                return {"total": len(self.candidates), "items": [{"candidate_id": c, "document_id": self.documents[c]} for c in self.candidates]}
            if method == "DELETE":
                return None
        raise AssertionError("Unexpected fake request")


def workload(**options):
    metrics = Measurements()
    api = API(metrics, **options)
    run = cli.Workload(api, metrics, cli.WorkloadConfig(items=2, concurrency=2))
    run.cleanup_metadata = AsyncMock()
    return run, api


def test_workload_completes_real_protocol_stages_before_scoped_cleanup():
    run, api = workload()
    run.run()
    report = run.report("passed")
    assert report["completed"] == 2 and report["queued_observed"] == 2
    assert report["cleanup"] == "completed"
    assert report["phases"]["workflow"]["samples"] == 2
    assert sum(method == "DELETE" for method, _ in api.calls) == 2
    run.cleanup_metadata.assert_awaited_once()
    text = json.dumps(report)
    assert "private.jwt.token" not in text and "candidate_id" not in text and api.org not in text


@pytest.mark.parametrize("options", [{"extraction": "failed"}, {"bad_scope": True}], ids=["worker-failure", "foreign-response"])
def test_failed_or_ambiguous_workflow_preserves_rows_for_review(options):
    run, api = workload(**options)
    with pytest.raises(BenchmarkFailure):
        run.run()
    assert run.report("failed")["cleanup"] == "manual_review_required"
    assert not any(method == "DELETE" for method, _ in api.calls)
    run.cleanup_metadata.assert_not_called()


def test_plan_never_registers_or_connects_to_database(monkeypatch, capsys):
    monkeypatch.setattr(cli.Workload, "run", lambda self: pytest.fail("writes attempted"))
    assert cli.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "plan"


def test_cleanup_queries_only_recorded_ids_and_identity(monkeypatch):
    run, _ = workload()
    real_cleanup = cli.Workload.cleanup_metadata.__get__(run)
    run.run()
    database = AsyncMock()
    class Transaction:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
    database.transaction = lambda: Transaction()
    async def execute(statement, *args):
        if statement.startswith(("DELETE FROM applications", "DELETE FROM candidates")):
            assert args[0] == UUID(run.organization) and len(args[1]) == 2
            return "DELETE 2"
        if statement.startswith("DELETE FROM jobs"):
            assert args == (UUID(run.organization), [UUID(run.job)])
        return "DELETE 1"
    database.execute.side_effect = execute
    monkeypatch.setattr(cli, "connection", AsyncMock(return_value=database))
    asyncio.run(real_cleanup())
    database.close.assert_awaited_once()
