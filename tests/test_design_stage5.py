import copy
import json
from pathlib import Path

import pytest

from scripts import design_acceptance as acceptance
from scripts import design_contract as contract

ROOT = Path(__file__).resolve().parents[1]


def delivery(tmp_path):
    """Exercise the frozen stage 5 validator on an explicit current-content fixture."""
    manifest = json.loads((ROOT / contract.MANIFEST).read_text(encoding="utf-8"))
    for name in manifest["feature_files"] + manifest["test_files"]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
        if name != contract.MANIFEST:
            manifest["sha256"][name] = contract.digest(target)
    (tmp_path / contract.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_historical_validator_fixture_matches_canonical_hashes_and_detects_edits(tmp_path):
    delivery(tmp_path)
    assert len(contract.source_digest(tmp_path)) == 64
    target = tmp_path / "app/web/assets/design.mjs"
    target.write_bytes(target.read_bytes() + b"// altered\n")
    with pytest.raises(ValueError, match="design_source_mismatch"):
        contract.load_manifest(tmp_path)


@pytest.mark.parametrize("name", ["../outside.py", "app\\private.py", "/absolute.py", "app/../other.py"])
def test_manifest_refuses_unsafe_paths(tmp_path, name):
    value = delivery(tmp_path)
    original = value["feature_files"][0]
    value["feature_files"][0] = name
    value["sha256"][name] = value["sha256"].pop(original)
    (tmp_path / contract.MANIFEST).write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe_design_source"):
        contract.load_manifest(tmp_path)


def test_plan_does_not_execute_commands_or_mutate_history(monkeypatch, capsys, tmp_path):
    delivery(tmp_path)
    original = contract.load_manifest
    monkeypatch.setattr(acceptance, "load_manifest", lambda _root: original(tmp_path))
    monkeypatch.setattr(acceptance, "source_digest", lambda _root: contract.source_digest(tmp_path))
    monkeypatch.setattr(acceptance, "verify_baseline", lambda *args: pytest.fail("plan must not execute"))
    assert acceptance.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["stage"] == 5 and result["executed"] is False
    assert "real-browser-design" in result["checks"]


@pytest.mark.parametrize("mutation", [None, "source", "cleanup", "missing", "duplicate", "failed"])
def test_browser_receipt_requires_complete_checks_and_current_source(tmp_path, mutation):
    expected = "a" * 64
    report = {"version": "design-browser-v1", "source_kind": "browser_synthetic_fixture", "source_sha256": expected,
              "status": "passed", "cleanup": "completed", "browser": "Chrome/test", "diagnostic": None,
              "checks": [{"name": name, "passed": True} for name in sorted(acceptance.BROWSER_CHECKS)]}
    value = copy.deepcopy(report)
    if mutation == "source":
        value["source_sha256"] = "b" * 64
    elif mutation == "cleanup":
        value["cleanup"] = "attention_required"
    elif mutation == "missing":
        value["checks"].pop()
    elif mutation == "duplicate":
        value["checks"][-1] = value["checks"][0]
    elif mutation == "failed":
        value["checks"][0]["passed"] = False
    path = tmp_path / "report.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    if mutation is None:
        assert len(acceptance.verify_browser_report(path, expected)["sha256"]) == 64
    else:
        with pytest.raises(ValueError, match="design_browser_acceptance_incomplete"):
            acceptance.verify_browser_report(path, expected)
