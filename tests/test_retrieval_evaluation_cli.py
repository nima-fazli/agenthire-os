import json
import subprocess
import sys

from scripts import retrieval_evaluation
from scripts.evaluation_cases import EXAMPLE_PATH, SUITE_PATH, load_example


def test_example_cli_writes_report_and_labels_it_as_an_example(tmp_path, capsys):
    output = tmp_path / "reports" / "quality.json"
    assert retrieval_evaluation.main(["--example", "--output", str(output)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["source_kind"] == "example" and printed["gate_passed"]
    assert json.loads(output.read_text()) == printed


def test_quality_regression_returns_one_and_still_exports_the_report(tmp_path, capsys):
    data = load_example().model_dump(mode="json")
    data["source_kind"] = "imported"
    data["ranking"][0]["ranked_ids"] = []
    path = tmp_path / "observations.json"
    path.write_text(json.dumps(data))
    assert retrieval_evaluation.main(["--observations", str(path)]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert not printed["gate_passed"] and printed["source_kind"] == "imported"


def test_stale_reference_hash_returns_two(tmp_path, capsys):
    data = load_example().model_dump(mode="json")
    data["suite_sha256"] = "0" * 64
    path = tmp_path / "observations.json"
    path.write_text(json.dumps(data))
    assert retrieval_evaluation.main(["--observations", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "SUITE_HASH_MISMATCH" in captured.err


def test_invalid_input_error_does_not_echo_private_content(tmp_path, capsys):
    data = load_example().model_dump(mode="json")
    data["private_resume"] = "private-resume-content-never-print"
    path = tmp_path / "observations.json"
    path.write_text(json.dumps(data))
    assert retrieval_evaluation.main(["--observations", str(path)]) == 2
    captured = capsys.readouterr()
    assert "private-resume-content" not in captured.err and captured.out == ""


def test_output_cannot_replace_suite_or_observations(tmp_path, capsys):
    for original, flag in ((SUITE_PATH, "--suite"), (EXAMPLE_PATH, "--observations")):
        path = tmp_path / original.name
        content = original.read_bytes()
        path.write_bytes(content)
        argv = (
            ["--example", "--suite", str(path)]
            if flag == "--suite"
            else ["--observations", str(path)]
        )
        assert retrieval_evaluation.main([*argv, "--output", str(path)]) == 2
        assert path.read_bytes() == content
    capsys.readouterr()


def test_missing_input_file_returns_two(tmp_path, capsys):
    assert (
        retrieval_evaluation.main(["--observations", str(tmp_path / "missing.json")])
        == 2
    )
    assert capsys.readouterr().out == ""


def test_example_cannot_masquerade_as_real_stack(tmp_path, capsys, monkeypatch):
    data = load_example().model_dump(mode="json")
    data["source_kind"] = "real_stack"
    path = tmp_path / "fake-example.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(retrieval_evaluation, "EXAMPLE_PATH", path)
    assert retrieval_evaluation.main(["--example"]) == 2
    assert capsys.readouterr().out == ""


def test_module_entrypoint_runs_without_network_or_stack():
    result = subprocess.run(
        [sys.executable, "-m", "scripts.retrieval_evaluation", "--example"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["source_kind"] == "example" and result.stderr == ""
