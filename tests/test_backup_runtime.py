import json

import pytest

from scripts.backup_run import normal_runtime
from scripts.backup_runtime import BackupFailure, validate_records
from tests.test_backup_run import Runner


def runtime(tmp_path):
    (tmp_path / ".env").write_text("fixture\n")
    runner = Runner(source="agenthire-os")
    return normal_runtime(tmp_path, runner=runner), runner


def test_original_ids_images_and_counts_are_preserved(tmp_path):
    source, runner = runtime(tmp_path)
    records = source.writers()
    source.call(("stop", "api", "extraction-worker", "embedding-worker"))
    source.stopped(records)
    source.resume(records)
    assert len(runner.started) == 4
    assert runner.started[-1] == runner.records[0]["id"]
    assert all(row["running"] for row in runner.records)
    assert "up" not in [part for call in runner.calls for part in call]


@pytest.mark.parametrize("change", ["project", "service", "image", "duplicate", "count"])
def test_changed_journal_cannot_start_arbitrary_container(tmp_path, change):
    source, runner = runtime(tmp_path)
    records = source.writers()
    if change == "project": records[0]["project"] = "foreign"
    elif change == "service": records[0]["service"] = "postgres"
    elif change == "image": records[0]["image"] = "sha256:" + "f" * 64
    elif change == "duplicate": records[1]["id"] = records[0]["id"]
    else: records.pop(1)
    with pytest.raises((ValueError, BackupFailure)):
        source.resume(records)
    assert runner.records[0]["id"] not in runner.started


def test_new_embedding_writer_is_detected_even_if_previously_absent(tmp_path):
    source, runner = runtime(tmp_path)
    records = source.writers()[:-1]
    for row in runner.records[:3]: row["running"] = False
    with pytest.raises(BackupFailure, match="not_stopped"):
        source.stopped(records)


def test_running_inventory_is_validated_before_recording(tmp_path):
    source, runner = runtime(tmp_path)
    runner.records[0]["project"] = "foreign"
    with pytest.raises(ValueError, match="ownership"):
        source.writers()
    assert not runner.started


def test_resume_inventory_rejects_unknown_metadata(tmp_path):
    source, _ = runtime(tmp_path)
    records = source.writers()
    records[0]["token"] = "PRIVATE"
    with pytest.raises(ValueError):
        validate_records(records, "agenthire-os")
    assert "PRIVATE" not in json.dumps([row for row in records if "token" not in row])
