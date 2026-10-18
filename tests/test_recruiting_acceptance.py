import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts import recruiting_acceptance as gate


def fixture_manifest(root):
    source = root / "app/fixture.py"
    source.parent.mkdir()
    source.write_bytes(b"value = 1\n")
    manifest = {"version": "recruiting-stage-2-v1", "base_commit": gate.BASE,
                "feature_files": ["app/fixture.py", gate.MANIFEST], "test_files": [],
                "sha256": {"app/fixture.py": gate.digest(source)}}
    path = root / gate.MANIFEST
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest, source, path


def test_copy_validation_accepts_windows_line_endings_and_detects_a_wrong_file(tmp_path):
    expected, source, _ = fixture_manifest(tmp_path)
    source.write_bytes(b"\xef\xbb\xbfvalue = 1\r\n\r\n")
    assert gate.load_manifest(tmp_path) == expected
    source.write_text("wrong file contents\n")
    with pytest.raises(ValueError, match="file_content_mismatch: app/fixture.py"):
        gate.load_manifest(tmp_path)


def test_manifest_rejects_private_paths_before_reading_or_staging_them(tmp_path):
    manifest, _, path = fixture_manifest(tmp_path)
    manifest["feature_files"].append(".env")
    manifest["sha256"][".env"] = "a" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="private_tracked_file"):
        gate.load_manifest(tmp_path)


def test_baseline_guard_rejects_a_different_branch_before_checks(tmp_path, monkeypatch):
    manifest, _, _ = fixture_manifest(tmp_path)
    def capture(_root, arguments):
        return str(tmp_path) if "--show-toplevel" in arguments else "other-branch"
    monkeypatch.setattr(gate, "capture", capture)
    with pytest.raises(ValueError, match="main_branch_required"):
        gate.verify_baseline(tmp_path, manifest)


def test_dry_run_never_starts_commands_or_commits(tmp_path, monkeypatch, capsys):
    fixture_manifest(tmp_path)
    fake_script = tmp_path / "scripts/recruiting_acceptance.py"
    monkeypatch.setattr(gate, "__file__", str(fake_script))
    monkeypatch.setattr(gate, "run", lambda *_: pytest.fail("dry-run mutation"))
    assert gate.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "plan" and result["executed"] is False


def test_a_failed_check_prevents_finalization(tmp_path, monkeypatch):
    fixture_manifest(tmp_path)
    (tmp_path.parent / "AgentHire_OS_Recovery_Current.md").write_text("Fixture\n")
    monkeypatch.setattr(gate, "__file__", str(tmp_path / "scripts/recruiting_acceptance.py"))
    monkeypatch.setattr(gate, "verify_baseline", lambda *_: None)
    monkeypatch.setattr(gate, "capture", lambda *_: "0016_document_embeddings (head)")
    monkeypatch.setattr(gate, "checks", lambda *_: [("failing-check", ["fixture-command"])])
    def fail(*_):
        raise RuntimeError("check_failed: fixture")
    monkeypatch.setattr(gate, "run", fail)
    monkeypatch.setattr(gate, "finalize", lambda *_: pytest.fail("must not finalize failed checks"))
    assert gate.main(["--execute", "--finalize"]) == 2


def test_git_commit_scopes_do_not_collect_unlisted_files(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(gate, "run", lambda _root, _label, arguments: commands.append(arguments))
    monkeypatch.setattr(gate, "capture", lambda *_: "a" * 40)
    manifest = {"feature_files": ["app/fixture.py"], "test_files": ["tests/fixture.py"]}
    with pytest.raises(ValueError):
        gate.finalize(tmp_path, manifest, [], Path("unused"))
    staged = [arguments for arguments in commands if arguments[:2] == ["git", "add"]]
    assert staged == [["git", "add", "--", "app/fixture.py"], ["git", "add", "--", "tests/fixture.py"]]
    assert all("--only" in arguments for arguments in commands if arguments[:2] == ["git", "commit"])


def test_archive_must_contain_the_tested_source_before_a_receipt_is_written(tmp_path, monkeypatch):
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("agenthire-os/app/fixture.py", "different source\n")
    bundle = {"status": "created", "executed": True, "working_tree_clean": True,
              "commit": "a" * 40, "output": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    monkeypatch.setattr(gate, "run", lambda *_: None)
    monkeypatch.setattr(gate, "capture", lambda _root, args: "a" * 40 if args[0] == "git" else json.dumps(bundle))
    manifest = {"feature_files": ["app/fixture.py"], "test_files": ["tests/fixture.py"],
                "sha256": {"app/fixture.py": gate.content_digest(b"tested source\n")}}
    receipt = tmp_path / "receipt.md"
    with pytest.raises(ValueError, match="committed_source_mismatch"):
        gate.finalize(tmp_path, manifest, [], receipt)
    assert not receipt.exists()
