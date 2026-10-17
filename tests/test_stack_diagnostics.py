import json
from types import SimpleNamespace

import pytest

from scripts import stack_diagnostics as cli


def rows():
    result = [{"ID": f"{i:064x}", "Service": name, "State": "running", "Health": "healthy",
               "Command": "private-command", "Name": "private-container"}
              for i, name in enumerate(("postgres", "api", "extraction-worker", "extraction-worker"), 1)]
    return [*result, {"ID": "f" * 64, "Service": "migrate", "State": "exited", "ExitCode": 0}]


def test_json_lines_and_legacy_array_are_supported_without_mutation():
    records = rows()
    assert cli.parse_inventory(json.dumps(records)) == records
    assert cli.parse_inventory("\n".join(map(json.dumps, records))) == records


@pytest.mark.parametrize(
    "text",
    ["private-secret", "{}", "null", '[{"Service":"api"}]', "x" * 1_048_577],
    ids=["invalid-json", "object", "null", "missing-container-id", "oversized-inventory"],
)
def test_invalid_inventory_is_rejected(text):
    with pytest.raises((ValueError, TypeError)):
        cli.parse_inventory(text)


def test_duplicate_container_cannot_inflate_replica_count():
    records = rows()
    records[3]["ID"] = records[2]["ID"]
    with pytest.raises(ValueError):
        cli.parse_inventory(json.dumps(records))


def test_host_diagnostic_only_lists_containers_and_emits_aggregates(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "repository_root", lambda path: path.resolve())
    calls = []

    def runner(command, **options):
        calls.append(command)
        assert options["timeout"] == 15 and options["check"] is False
        return SimpleNamespace(returncode=0, stdout=json.dumps(rows()))

    report = cli.collect(tmp_path, runner=runner)
    assert report["status"] == "ok" and len(calls) == 1
    assert calls[0][-4:] == ("ps", "--all", "--format", "json")
    assert "private" not in json.dumps(report)
    assert report["services"]["extraction-worker"]["healthy"] == 2


def test_cli_hides_docker_errors(monkeypatch, capsys):
    def fail(*_, **__):
        raise OSError("private-docker-detail")

    monkeypatch.setattr(cli, "collect", fail)
    assert cli.main([]) == 2
    assert "private" not in capsys.readouterr().out
