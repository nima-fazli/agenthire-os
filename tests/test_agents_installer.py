import json
from pathlib import Path

import pytest

from scripts import update_installer as installer


@pytest.fixture
def package(tmp_path, monkeypatch):
    project = tmp_path / "project"
    bundle = tmp_path / "bundle"
    project.mkdir()
    bundle.mkdir()
    for name, raw in {
        "pyproject.toml": b"project",
        "migrations/versions/0017_access_sessions.py": b"baseline",
        "app/one.py": b"old\n",
    }.items():
        p = project / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
    items = []
    for name, data, old in [
        ("app/one.py", b"new\n", b"old\n"),
        ("app/two.py", b"second\n", None),
    ]:
        p = bundle / "payload" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        items.append(
            {
                "path": name,
                "sha256": installer.digest(data),
                "before_normalized_sha256": installer.digest(installer.normalized(old))
                if old
                else None,
            }
        )
    (bundle / "manifest.json").write_text(json.dumps({"files": items}))
    monkeypatch.setattr(installer, "BUNDLE", bundle)
    return project, bundle


def test_preflight_apply_and_idempotent_retry_preserve_private_configuration(package):
    project, _ = package
    (project / ".env").write_text("private=preserve")
    assert (
        installer.install(project)["status"] == "ready"
        and (project / "app/one.py").read_bytes() == b"old\n"
    )
    result = installer.install(project, True, True)
    assert (
        result["status"] == "installed"
        and (Path(result["backup"]) / "files/app/one.py").read_bytes() == b"old\n"
    )
    assert (project / ".env").read_text() == "private=preserve" and installer.install(
        project
    )["status"] == "up_to_date"


def test_unknown_local_edits_are_never_overwritten(package):
    project, _ = package
    (project / "app/one.py").write_bytes(b"my edit")
    result = installer.install(project, True, True)
    assert (
        result["status"] == "blocked"
        and result["conflicts"] == ["app/one.py"]
        and not (project / "app/two.py").exists()
    )


def test_crlf_and_bom_are_accepted_as_the_same_reviewed_source(package):
    project, _ = package
    (project / "app/one.py").write_bytes(b"\xef\xbb\xbfold\r\n")
    assert installer.install(project)["status"] == "ready"


def test_damaged_payload_cannot_mutate_the_project(package):
    project, bundle = package
    (bundle / "payload/app/two.py").write_bytes(b"damaged")
    with pytest.raises(ValueError, match="damaged"):
        installer.install(project, True, True)
    assert (project / "app/one.py").read_bytes() == b"old\n"


def test_database_backup_failure_prevents_all_file_changes(package, monkeypatch):
    project, _ = package

    def failed(*_):
        raise ValueError("Synthetic backup failure")

    monkeypatch.setattr(installer, "backup_database", failed)
    with pytest.raises(ValueError):
        installer.install(project, True)
    assert (project / "app/one.py").read_bytes() == b"old\n" and not (
        project / "app/two.py"
    ).exists()


def test_interrupted_writes_restore_completed_files(package, monkeypatch):
    project, _ = package
    write = installer.atomic_write
    attempt = 0

    def fail_second(path, data):
        nonlocal attempt
        attempt += 1
        if attempt == 2:
            raise OSError("Synthetic write failure")
        return write(path, data)

    monkeypatch.setattr(installer, "atomic_write", fail_second)
    with pytest.raises(OSError):
        installer.install(project, True, True)
    assert (project / "app/one.py").read_bytes() == b"old\n" and not (
        project / "app/two.py"
    ).exists()


@pytest.mark.parametrize(
    "name",
    [
        "../escape.py",
        "/absolute.py",
        ".env",
        ".git/config",
        "storage/private.pdf",
        r"app\bad.py",
    ],
)
def test_unsafe_targets_are_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        installer.safe_target(tmp_path, name)
