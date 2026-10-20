import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import ai_quality_acceptance as module
from scripts.ai_quality_run import plan, save_report
from scripts.recruiting_acceptance import digest
from scripts.source_bundle import checked_path
from tests.test_ai_quality_metrics import report


def stage4_fixture(tmp_path):
    """Exercise the stage 4 gate on a self-contained fixture after later UI changes."""
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / module.MANIFEST).read_text(encoding="utf-8"))
    paths = manifest["feature_files"] + manifest["test_files"]
    for name in paths:
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((root / name).read_bytes())
        if name != module.MANIFEST:
            manifest["sha256"][name] = digest(destination)
    (tmp_path / module.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def test_delivered_manifest_is_complete_and_detects_modified_code(tmp_path):
    root = stage4_fixture(tmp_path)
    manifest = module.load_manifest(root)
    paths = manifest["feature_files"] + manifest["test_files"]
    assert 20 <= len(paths) <= module.MAX_STAGE_FILES and len(set(paths)) == len(paths)
    assert "compose.quality.yaml" in paths and checked_path("compose.quality.yaml")
    changed = root / "scripts/ai_quality_metrics.py"
    changed.write_bytes(changed.read_bytes() + b"# changed\n")
    with pytest.raises(ValueError, match="source_mismatch"):
        module.load_manifest(root)


def test_manifest_canonical_hash_accepts_windows_newlines_and_bom(tmp_path):
    path = tmp_path / "code.py"
    path.write_bytes(b"one\ntwo\n")
    expected = digest(path)
    path.write_bytes(b"\xef\xbb\xbfone\r\ntwo\r\n")
    assert digest(path) == expected


@pytest.mark.parametrize("mutation", [None, "fixture", "cleanup", "checks", "hash"])
def test_finalizer_requires_untampered_real_model_receipt(tmp_path, mutation):
    root = tmp_path / "agenthire-os"
    root.mkdir()
    project = "agenthire-ci-" + "a" * 32
    _, steps = plan(root, project, root / "unused")
    value = {"version": "ai-quality-run-v1", "project": project, "status": "passed", "diagnostic": None,
             "cleanup": "completed", "checks": [{"name": name, "exit": 0} for name, _, _ in steps],
             "measurement": report(kind="fixture" if mutation == "fixture" else "live")}
    if mutation == "cleanup":
        value["cleanup"] = "attention_required"
    if mutation == "checks":
        value["checks"].pop()
    saved = save_report(tmp_path / "AgentHire_OS_Quality_Reports", value)
    if mutation == "hash":
        Path(saved["path"]).write_text(json.dumps(copy.deepcopy(value)) + " ")
        assert hashlib.sha256(Path(saved["path"]).read_bytes()).hexdigest() != saved["sha256"]
    if mutation is None:
        module.verify_saved_quality(root, saved)
    else:
        with pytest.raises(ValueError):
            module.verify_saved_quality(root, saved)


def test_acceptance_plan_has_no_mutation_or_commits(monkeypatch, capsys, tmp_path):
    fixture = stage4_fixture(tmp_path)
    original = module.load_manifest
    monkeypatch.setattr(module, "load_manifest", lambda _root: original(fixture))
    monkeypatch.setattr(module, "verify_baseline", lambda *args: pytest.fail("plan must not run"))
    monkeypatch.setattr(module, "live_gate", lambda *args: pytest.fail("plan must not run"))
    assert module.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["stage"] == 4 and result["executed"] is False
    assert "live-quality-and-cleanup" in result["checks"]


def test_native_receipt_updates_both_recovery_files_without_duplicate_entries(tmp_path):
    current = tmp_path / "AgentHire_OS_Recovery_Current.md"
    complete = tmp_path / "AgentHire_OS_Recovery_Complete.md"
    for path in (current, complete):
        path.write_text("# Recovery\n", encoding="utf-8")
    commit = "a" * 40
    receipt = ["", "## Stage 4 native acceptance receipt", f"Test commit: {commit}", ""]
    module.append_receipts(current, receipt, commit)
    module.append_receipts(current, receipt, commit)
    for path in (current, complete):
        assert path.read_text(encoding="utf-8").count(f"Test commit: {commit}") == 1
