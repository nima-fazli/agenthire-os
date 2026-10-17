import hashlib
import io
import json
import os
import stat
import zipfile
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.core import recovery_archive as archive


def objects(root):
    rows = []
    for index in range(2):
        data = b"%PDF-1.7\nsynthetic " + str(index).encode() + b"\n%%EOF"
        key = f"{index:032x}.pdf"
        (root / key).write_bytes(data)
        rows.append({"key": key, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return rows


def payload(root, rows):
    handle = io.BytesIO()
    archive.export_objects(root, rows, handle)
    handle.seek(0)
    return handle


def test_roundtrip_checks_database_catalog_and_preserves_bytes(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    rows = objects(source)
    handle = payload(source, rows)
    assert archive.validate_archive(handle, list(reversed(rows))) == rows
    assert archive.import_objects(handle, target, rows) == {"objects": 2, "bytes": sum(row["size"] for row in rows)}
    assert {path.name: path.read_bytes() for path in source.iterdir()} == {
        path.name: path.read_bytes() for path in target.iterdir()}
    with pytest.raises(ValueError, match="empty"):
        archive.import_objects(handle, target, rows)


def test_roundtrip_with_windows_directory_entry_metadata(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    rows = objects(source)
    real_scandir = os.scandir

    class WindowsEntry:
        def __init__(self, entry):
            self.name = entry.name
            self.path = entry.path
            self.entry = entry

        def stat(self, *, follow_symlinks=True):
            info = self.entry.stat(follow_symlinks=follow_symlinks)
            return SimpleNamespace(st_mode=info.st_mode, st_nlink=0)

    @contextmanager
    def windows_scandir(path):
        with real_scandir(path) as entries:
            yield (WindowsEntry(entry) for entry in entries)

    monkeypatch.setattr(archive.os, "scandir", windows_scandir)
    handle = payload(source, rows)
    assert archive.import_objects(handle, target, rows) == {
        "objects": 2, "bytes": sum(row["size"] for row in rows)
    }
    for row in rows:
        assert (target / row["key"]).read_bytes() == (source / row["key"]).read_bytes()


@pytest.mark.parametrize("operation", ["scan", "open_object"])
def test_hardlinked_storage_objects_are_rejected(tmp_path, operation):
    root = tmp_path / "objects"
    root.mkdir()
    rows = objects(root)
    os.link(root / rows[0]["key"], tmp_path / "alias.pdf")
    with pytest.raises(ValueError, match="Unsafe recovery"):
        if operation == "scan":
            archive.export_objects(root, rows, io.BytesIO())
        else:
            with archive.open_object(root, rows[0]):
                pass


def test_export_supports_nonseekable_docker_stdout(tmp_path):
    rows = objects(tmp_path)
    class Pipe:
        def __init__(self): self.parts = []
        def write(self, data):
            self.parts.append(bytes(data))
            return len(data)
        def flush(self): pass
    pipe = Pipe()
    archive.export_objects(tmp_path, rows, pipe)
    assert archive.validate_archive(io.BytesIO(b"".join(pipe.parts)), rows) == rows


@pytest.mark.parametrize("change", ["path", "duplicate", "size_bool", "sha", "extra", "limit"])
def test_invalid_catalog_is_rejected(tmp_path, monkeypatch, change):
    rows = objects(tmp_path)
    if change == "path":
        rows[0]["key"] = "../private.pdf"
    elif change == "duplicate":
        rows.append(dict(rows[0]))
    elif change == "size_bool":
        rows[0]["size"] = True
    elif change == "sha":
        rows[0]["sha256"] = "A" * 64
    elif change == "extra":
        rows[0]["filename"] = "private.pdf"
    else:
        monkeypatch.setattr(archive, "MAX_BYTES", 1)
    with pytest.raises(ValueError):
        archive.catalog(rows)


@pytest.mark.parametrize("failure", ["missing", "changed", "orphan", "directory"])
def test_export_rejects_inconsistent_storage(tmp_path, failure):
    rows = objects(tmp_path)
    path = tmp_path / rows[0]["key"]
    if failure == "missing":
        path.unlink()
    elif failure == "changed":
        path.write_bytes(b"x" * rows[0]["size"])
    elif failure == "orphan":
        (tmp_path / ("f" * 32 + ".pdf")).write_bytes(b"orphan")
    else:
        path.unlink()
        path.mkdir()
    with pytest.raises(ValueError):
        archive.export_objects(tmp_path, rows, io.BytesIO())


@pytest.mark.parametrize("failure", ["traversal", "absolute", "windows", "symlink", "compressed", "digest", "metadata"])
def test_unsafe_archive_is_rejected_before_writing(tmp_path, failure):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    rows = objects(source)
    handle = io.BytesIO()
    metadata = json.dumps({"format": archive.FORMAT, "objects": rows})
    if failure == "metadata":
        metadata = '{"format":"wrong","format":"agenthire-pdf-snapshot-v1","objects":[]}'
    with zipfile.ZipFile(handle, "w") as output:
        output.writestr("objects.json", metadata)
        for row in rows:
            data = (source / row["key"]).read_bytes()
            if failure == "digest":
                data = b"x" * len(data)
            output.writestr("objects/" + row["key"], data,
                            compress_type=zipfile.ZIP_DEFLATED if failure == "compressed" else zipfile.ZIP_STORED)
        extra = {"traversal": "../escape.pdf", "absolute": "/escape.pdf", "windows": "C:\\escape.pdf"}.get(failure)
        if extra:
            output.writestr(extra, b"private")
        if failure == "symlink":
            info = zipfile.ZipInfo("link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            output.writestr(info, b"outside")
    with pytest.raises(ValueError):
        archive.import_objects(handle, target, rows)
    assert list(target.iterdir()) == []
    assert not (tmp_path / "escape.pdf").exists()


def test_database_disagreement_and_archive_budget_fail_before_writes(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    rows = objects(source)
    handle = payload(source, rows)
    with pytest.raises(ValueError, match="disagree"):
        archive.import_objects(handle, target, rows[:1])
    monkeypatch.setattr(archive, "MAX_ARCHIVE", 8)
    with pytest.raises(ValueError, match="limit"):
        archive.import_objects(handle, target, rows)
    assert list(target.iterdir()) == []
