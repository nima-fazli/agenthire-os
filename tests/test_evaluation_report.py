import json
import os
from pathlib import Path

import pytest

from app.services.retrieval_evaluation import RetrievalEvaluationService
from scripts.evaluation_cases import load_example, load_suite
from scripts.evaluation_report import (
    MAX_INPUT_BYTES,
    EvaluationFileError,
    read_json,
    write_report,
)


@pytest.mark.parametrize(
    "raw",
    [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"nested":{"a":1,"a":2}}'],
)
def test_ambiguous_or_nonfinite_json_is_rejected(tmp_path: Path, raw):
    path = tmp_path / "input.json"
    path.write_bytes(raw)
    with pytest.raises(EvaluationFileError):
        read_json(path)


def test_input_byte_limit_is_enforced_before_parsing(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b" " * (MAX_INPUT_BYTES + 1))
    with pytest.raises(EvaluationFileError):
        read_json(path)


def test_utf8_bom_and_persian_text_round_trip(tmp_path):
    path = tmp_path / "utf8.json"
    path.write_text('{"value":"کیان"}', encoding="utf-8-sig")
    assert read_json(path) == {"value": "کیان"}


def test_report_is_complete_atomic_json_with_private_file_permissions(tmp_path):
    report = RetrievalEvaluationService().evaluate(load_suite(), load_example())
    path = tmp_path / "reports" / "quality.json"
    write_report(path, report)
    assert read_json(path) == json.loads(report.model_dump_json())
    assert list(path.parent.iterdir()) == [path]
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_replace_failure_preserves_previous_report_and_removes_temporary_file(
    tmp_path, monkeypatch
):
    path = tmp_path / "quality.json"
    path.write_text("previous", encoding="utf-8")
    report = RetrievalEvaluationService().evaluate(load_suite(), load_example())

    def fail(*_):
        raise OSError("unavailable")

    monkeypatch.setattr("scripts.evaluation_report.os.replace", fail)
    with pytest.raises(OSError):
        write_report(path, report)
    assert path.read_text() == "previous" and list(tmp_path.iterdir()) == [path]
