import json

import pytest

from app.core.document_reconciliation import ReconciliationError
from app.services.document_reconciliation import ReconciliationOutcome
from scripts import reconcile_documents as cli

KEY = "a" * 32 + ".pdf"


@pytest.mark.parametrize(
    "args",
    [
        ["--apply"],
        ["--key", "../outside"],
        ["--key", KEY, "--key", KEY],
        ["--min-age-days", "0"],
        ["--min-age-days", "366"],
        ["--min-age-days", "word"],
    ],
    ids=["scope", "path", "duplicate", "young", "old", "invalid"],
)
def test_invalid_cli_arguments_stop_before_connection(args, monkeypatch):
    async def forbidden(*_):
        pytest.fail("A database connection must not be attempted.")

    monkeypatch.setattr(cli, "reconcile", forbidden)
    with pytest.raises(SystemExit) as result:
        cli.main(args)
    assert result.value.code == 2


def test_cli_defaults_to_dry_run_and_streams_private_operator_journal(
    monkeypatch, capsys
):
    async def fake(args, emit):
        assert not args.apply and args.min_age_days == 7
        emit(ReconciliationOutcome(KEY, "would_delete"))

    monkeypatch.setattr(cli, "reconcile", fake)
    assert cli.main([]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["action"] == "would_delete"
    assert lines[-1] == {
        "event": "summary",
        "mode": "dry_run",
        "ok": True,
        "counts": {"would_delete": 1},
    }


@pytest.mark.parametrize("action", ["delete_failed", "referenced_missing"])
def test_incomplete_reconciliation_returns_failure(action, monkeypatch, capsys):
    async def fake(args, emit):
        emit(ReconciliationOutcome(KEY, action))

    monkeypatch.setattr(cli, "reconcile", fake)
    assert cli.main(["--key", KEY, "--apply"]) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["ok"] is False


def test_partial_failure_preserves_journal_and_hides_exception_details(
    monkeypatch, capsys
):
    async def fake(args, emit):
        emit(ReconciliationOutcome(KEY, "deleted"))
        raise ReconciliationError("synthetic-secret-and-private-path")

    monkeypatch.setattr(cli, "reconcile", fake)
    assert cli.main(["--key", KEY, "--apply"]) == 1
    output = capsys.readouterr()
    assert "synthetic-secret" not in output.out + output.err
    assert json.loads(output.out.splitlines()[-1])["counts"] == {"deleted": 1}
