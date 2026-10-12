import os
from pathlib import Path

import pytest

from app.core.document_reconciliation import (
    ReconciliationError,
    ReconciliationStorage,
    validate_key,
)

KEY = "a" * 32 + ".pdf"


@pytest.mark.parametrize("key", [KEY, ".upload-123abc_x"])
def test_managed_names_are_accepted(key):
    validate_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "../outside.pdf",
        "/etc/passwd",
        "a.pdf",
        KEY + "\n",
        ".upload-123456789",
        "A" * 32 + ".pdf",
    ],
)
def test_untrusted_names_are_rejected(key):
    with pytest.raises(ReconciliationError):
        validate_key(key)


def test_inventory_is_non_recursive_and_keeps_unknown_files(tmp_path):
    (tmp_path / KEY).write_bytes(b"private")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / KEY).write_bytes(b"inside")
    (tmp_path / "operator-note.txt").write_text("keep")
    store = ReconciliationStorage(tmp_path)
    assert store.keys() == (KEY,)
    state = store.inspect(KEY)
    assert state.safe and store.remove_if_unchanged(KEY, state)
    assert (nested / KEY).read_bytes() == b"inside"
    assert (tmp_path / "operator-note.txt").read_text() == "keep"
    assert store.inspect(KEY) is None


def test_modified_file_is_not_deleted(tmp_path):
    path = tmp_path / KEY
    path.write_bytes(b"old")
    store = ReconciliationStorage(tmp_path)
    state = store.inspect(KEY)
    path.write_bytes(b"changed")
    assert not store.remove_if_unchanged(KEY, state)
    assert path.read_bytes() == b"changed"


def test_missing_file_and_managed_directory_are_not_deleted(tmp_path):
    store = ReconciliationStorage(tmp_path)
    assert store.inspect(KEY) is None
    (tmp_path / KEY).mkdir()
    state = store.inspect(KEY)
    assert not state.safe and not store.remove_if_unchanged(KEY, state)


def test_hardlink_is_not_deleted(tmp_path):
    source = tmp_path / "outside.txt"
    source.write_bytes(b"keep")
    os.link(source, tmp_path / KEY)
    store = ReconciliationStorage(tmp_path)
    state = store.inspect(KEY)
    assert not state.safe and not store.remove_if_unchanged(KEY, state)
    assert source.read_bytes() == b"keep"


def test_symlink_and_root_replacement_are_refused(tmp_path, monkeypatch):
    root = tmp_path / "private"
    root.mkdir()
    (root / KEY).write_bytes(b"keep")
    store = ReconciliationStorage(root)
    state = store.inspect(KEY)
    # Unit-level simulation is portable; the Docker smoke uses real symlinks.
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == root or original(path))
    with pytest.raises(ReconciliationError):
        store.remove_if_unchanged(KEY, state)
    monkeypatch.setattr(Path, "is_symlink", original)
    root.rename(tmp_path / "old")
    root.mkdir()
    (root / KEY).write_bytes(b"new")
    with pytest.raises(ReconciliationError, match="changed"):
        store.remove_if_unchanged(KEY, state)
    assert (root / KEY).read_bytes() == b"new"


def test_global_root_is_refused():
    with pytest.raises(ReconciliationError):
        ReconciliationStorage(Path(Path.cwd().anchor)).keys()


def test_inventory_limit_fails_without_deleting(tmp_path, monkeypatch):
    import app.core.document_reconciliation as core

    monkeypatch.setattr(core, "MAX_KEYS", 1)
    for char in "ab":
        (tmp_path / (char * 32 + ".pdf")).write_bytes(b"keep")
    with pytest.raises(ReconciliationError, match="exact keys"):
        ReconciliationStorage(tmp_path).keys()
    assert len(list(tmp_path.iterdir())) == 2
