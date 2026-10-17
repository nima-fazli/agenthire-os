import json
from types import SimpleNamespace

import pytest

from scripts import resource_watch as cli


def test_stats_are_matched_to_private_ids_then_stripped_to_services():
    containers = {"a" * 64: "api", "b" * 64: "ollama"}
    output = "\n".join(json.dumps({"ID": key[:12], "Name": "private-container", "CPUPerc": "1.5%",
                                  "MemUsage": "12MiB / 3GiB"}) for key in containers)
    def runner(command, **options):
        assert command[:3] == ("docker", "stats", "--no-stream")
        assert options["timeout"] == 5 and not options["check"]
        return SimpleNamespace(returncode=0, stdout=output, stderr="private-stderr")
    result = cli.snapshot(containers, runner=runner)
    assert set(result) == {"api", "ollama"}
    assert "private" not in json.dumps(result) and "ID" not in json.dumps(result)


@pytest.mark.parametrize("identities", [["c" * 12], ["a" * 12, "a" * 12], []], ids=["foreign", "duplicate", "missing"])
def test_incomplete_or_foreign_stats_do_not_create_a_valid_sample(identities):
    output = "\n".join(json.dumps({"ID": key, "CPUPerc": "1%", "MemUsage": "1MiB / 2GiB"}) for key in identities)
    with pytest.raises(ValueError):
        cli.snapshot({"a" * 64: "api"}, runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout=output))


def test_docker_failure_is_sanitized(monkeypatch, capsys):
    monkeypatch.setattr(cli, "watch", lambda *a, **k: (_ for _ in ()).throw(OSError("private-env-token")))
    assert cli.main([]) == 2
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "unavailable" and "private" not in output
