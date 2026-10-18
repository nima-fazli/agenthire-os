import json

import pytest

from scripts import backup_smoke as module
from tests.test_backup_run import Runner
from tests.test_backup_run import setup as setup  # noqa: PLC0414


@pytest.mark.parametrize("failure", [None, "occupied-source", "occupied-target", "build", "dump", "resume", "target", "restore", "fingerprint", "api", "cleanup", "source-cleanup"])
def test_synthetic_gate_never_targets_normal_stack_and_requires_all_cleanup(setup, failure, capsys):
    repository, _store, archive = setup
    runner = Runner(archive, failure)
    code = module.main(["--execute"], runner=runner)
    text = capsys.readouterr().out
    report = json.loads(text)
    assert code == (0 if failure is None else 1)
    assert report["normal_stack_touched"] is False
    assert "PRIVATE" not in text
    assert (repository / ".env").read_text() == "PRIVATE-HOST-ENVIRONMENT\n"
    assert not any("agenthire-os" in command for command in runner.calls)
    cleanup = [command for command in runner.calls if "down" in command]
    if failure == "occupied-source":
        assert not cleanup
        assert not any("build" in command for command in runner.calls)
    elif failure in {"build", "dump", "resume", "occupied-target"}:
        assert len(cleanup) == 1
    else:
        assert len(cleanup) == 2
    if failure is None:
        assert report["source_cleanup"] == report["isolated_restore_cleanup"] == "completed"
        assert report["restore_receipt_created"] is True
        assert report["retained_after_gate"] is False
    if failure == "cleanup":
        assert report["isolated_restore_cleanup"] == "attention"
        assert len(report["owned_projects"]) == 2
    if failure == "source-cleanup":
        assert report["source_cleanup"] == "attention"
