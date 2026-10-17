import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.runtime_health import RuntimeHealthRepository
from scripts import runtime_diagnostics as cli


def test_repository_uses_read_only_deadlines_and_returns_only_aggregates():
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = ["head"]
    result.mappings.return_value.all.return_value = [{
        "queue": "extraction", "queued": 2, "running": 1,
        "expired_leases": 1, "oldest_queued_seconds": 15,
    }]
    session.execute.return_value = result

    async def run():
        repository = RuntimeHealthRepository(session)
        await repository.configure()
        assert await repository.migration_heads() == frozenset({"head"})
        return await repository.queues()

    assert asyncio.run(run())["extraction"]["expired_leases"] == 1
    sql = [str(call.args[0]) for call in session.execute.await_args_list]
    assert sql[:3] == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout = '1000ms'",
        "SET LOCAL lock_timeout = '500ms'",
    ]
    query = sql[-1]
    assert "statement_timestamp()" in query and "UNION ALL" in query
    assert "SELECT *" not in query and "failure_code" not in query
    session.commit.assert_not_called()


@pytest.mark.parametrize("report,code", [
    ({"status": "ready"}, 0),
    ({"status": "not_ready"}, 1),
    ({"status": "ready", "queues": "unavailable"}, 1),
], ids=["ready", "not_ready", "queue_failure"])
def test_operator_cli_exit_codes_and_json(report, code, monkeypatch, capsys):
    async def fake(*, queues):
        assert queues
        return report

    monkeypatch.setattr(cli, "collect", fake)
    assert cli.main(["--queues"]) == code
    assert json.loads(capsys.readouterr().out) == report


def test_operator_cli_hides_configuration_and_transport_error(monkeypatch, capsys):
    async def fail(**_):
        raise OSError("synthetic-private-host-password")

    monkeypatch.setattr(cli, "collect", fail)
    assert cli.main([]) == 1
    output = capsys.readouterr()
    assert "private" not in output.out + output.err
    assert json.loads(output.out)["diagnostic"] == "unavailable"


def test_queue_timeout_closes_session():
    session = MagicMock(spec=AsyncSession)
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False
    session.execute = AsyncMock(side_effect=TimeoutError)
    assert asyncio.run(cli.queue_report(MagicMock(return_value=session))) == "unavailable"
    session.__aexit__.assert_awaited_once()


def test_queue_policy_can_fail_operator_check_without_relabeling_core_readiness(monkeypatch, capsys):
    async def fake(**_):
        return {"status": "ready", "queues": {
            name: {"queued": 2, "running": 1, "expired_leases": 1, "oldest_queued_seconds": 61}
            for name in ("extraction", "embedding")}}

    monkeypatch.setattr(cli, "collect", fake)
    assert cli.main(["--queues", "--max-queue-age-seconds", "60", "--max-expired-leases", "0"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ready" and report["queue_policy"]["status"] == "attention"


@pytest.mark.parametrize("arguments", [["--max-expired-leases", "0"], ["--queues", "--max-queue-age-seconds", "-1"]])
def test_invalid_queue_policy_does_not_open_database(arguments, monkeypatch, capsys):
    async def forbidden(**_):
        pytest.fail("Invalid arguments must not open the database")

    monkeypatch.setattr(cli, "collect", forbidden)
    assert cli.main(arguments) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "not_ready"
