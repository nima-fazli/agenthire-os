import json
import subprocess
import zipfile

import pytest

from scripts import source_bundle as cli


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    files = {name: b"source" for name in cli.REQUIRED}
    files["pyproject.toml"] = b'[project]\nname = "agenthire-os"\n'
    files[".env.example"] = b"AGENTHIRE_ENVIRONMENT=local\n"
    calls = []
    state = {"dirty": False, "mode": b"100644"}

    def git(path, *args, allowed=(0,)):
        assert path == root
        calls.append(args)
        if args == ("rev-parse", "--show-toplevel"): value = str(root).encode()
        elif args == ("rev-parse", "HEAD"): value = b"a" * 40
        elif args[:1] == ("ls-tree",):
            value = b"".join(state["mode"] + b" blob " + b"b" * 40 + b"\t" + n.encode() + b"\0" for n in files)
        elif args == ("show", "HEAD:pyproject.toml"): value = files["pyproject.toml"]
        elif args[:1] == ("diff",):
            return subprocess.CompletedProcess(args, int(state["dirty"]), b"", b"")
        elif args[:1] == ("archive",):
            target = next(a.split("=", 1)[1] for a in args if a.startswith("--output="))
            with zipfile.ZipFile(target, "w") as archive:
                for name, data in files.items(): archive.writestr(cli.PREFIX + name, data)
            value = b""
        else: raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, value, b"")

    monkeypatch.setattr(cli, "_git", git)
    return root, files, state, calls


def test_plan_creates_no_files_and_does_not_export(source):
    root, _, state, calls = source
    state["dirty"] = True
    result = cli.bundle(root)
    assert not result["executed"] and not result["working_tree_clean"]
    assert not any(args[0] == "archive" for args in calls)
    assert not list(root.parent.glob("*.zip"))


def test_export_contains_every_committed_file_ci_and_a_hash_manifest(source):
    root, files, _, _ = source
    result = cli.bundle(root, execute=True)
    with zipfile.ZipFile(result["output"]) as archive:
        assert set(archive.namelist()) == {cli.PREFIX + name for name in files} | {cli.MANIFEST}
        manifest = json.loads(archive.read(cli.MANIFEST))
        assert manifest["commit"] == "a" * 40 and manifest["file_count"] == len(files)
        assert ".github/workflows/verify.yml" in manifest["files"]
        assert ".env.example" in manifest["files"]
    assert len(result["sha256"]) == 64
    assert not list(root.parent.glob(".agenthire-source-*"))


@pytest.mark.parametrize("name", [
    ".env", "app/.env.production", "storage/resume.pdf", "docs/AgentHire_OS_Recovery.md",
    "docs/private.docx", "app/key.pem", "app/../private.py", "app\\private.py", "/app/private.py",
])
def test_private_or_unsafe_tracked_files_are_rejected(source, name):
    root, files, _, _ = source
    files[name] = b"private"
    with pytest.raises(ValueError): cli.bundle(root, execute=True)
    assert not list(root.parent.glob("*.zip"))


@pytest.mark.parametrize("problem", ["dirty", "symlink", "missing_ci"])
def test_export_requires_clean_regular_complete_committed_source(source, problem):
    root, files, state, _ = source
    if problem == "dirty": state["dirty"] = True
    elif problem == "symlink": state["mode"] = b"120000"
    else: del files[".github/dependabot.yml"]
    with pytest.raises(ValueError): cli.bundle(root, execute=True)


def test_existing_output_is_preserved_and_in_repository_output_is_rejected(source):
    root, _, _, _ = source
    output = root.parent / "existing.zip"
    output.write_bytes(b"keep")
    with pytest.raises(ValueError): cli.bundle(root, output, execute=True)
    assert output.read_bytes() == b"keep"
    with pytest.raises(ValueError): cli.bundle(root, root / "source.zip", execute=True)


def test_archive_omission_is_rejected_before_publication(tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(cli.PREFIX + "README.md", b"source")
    with pytest.raises(ValueError): cli.add_manifest(path, "a" * 40, ("README.md", "Dockerfile"))


def test_cli_reports_a_safe_actionable_failure(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise cli.BundleError("uncommitted_source_changes")
    monkeypatch.setattr(cli, "bundle", fail)
    assert cli.main([]) == 2
    assert json.loads(capsys.readouterr().out)["diagnostic"] == "uncommitted_source_changes"


def test_git_failure_output_is_not_exposed(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs:
        subprocess.CompletedProcess(args, 128, b"PRIVATE_OUTPUT", b"PRIVATE_ERROR"))
    with pytest.raises(cli.BundleError, match="git_source_inspection_failed") as caught:
        cli._git(tmp_path, "rev-parse", "HEAD")
    assert "PRIVATE" not in str(caught.value)
