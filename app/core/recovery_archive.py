"""Bounded flat PDF archives; never extract archive paths directly."""

import hashlib
import json
import os
import re
import stat
import zipfile
from pathlib import Path

MAX_OBJECTS = 1000
MAX_BYTES = 128 * 1024 * 1024
MAX_METADATA = 512 * 1024
MAX_ARCHIVE = MAX_BYTES + 2 * MAX_METADATA
FORMAT = "agenthire-pdf-snapshot-v1"


def catalog(rows):
    if not isinstance(rows, (list, tuple)) or len(rows) > MAX_OBJECTS:
        raise ValueError("Invalid recovery catalog.")
    result, keys, total = [], set(), 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"key", "size", "sha256"}:
            raise ValueError("Invalid recovery record.")
        key, size, digest = row["key"], row["size"], row["sha256"]
        if (not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{32}\.pdf", key)
                or key in keys or type(size) is not int or not 1 <= size <= 50 * 1024 * 1024
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("Invalid recovery object.")
        keys.add(key)
        total += size
        result.append(dict(row))
    if total > MAX_BYTES:
        raise ValueError("Recovery byte limit exceeded.")
    return sorted(result, key=lambda row: row["key"])


def storage_root(root):
    root = Path(os.path.abspath(root))
    if root == Path(root.anchor) or any(path.is_symlink() for path in (root, *root.parents)) or not root.is_dir():
        raise ValueError("Invalid recovery storage.")
    return root


def scan(root, rows):
    root = storage_root(root)
    expected = {row["key"] for row in rows}
    observed = set()
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.name not in expected:
                raise ValueError("Unexpected recovery storage entry.")
            # DirEntry.stat() reports st_nlink=0 on Windows; fetch full metadata.
            info = os.stat(entry.path, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Unsafe recovery storage object.")
            observed.add(entry.name)
    if observed != expected:
        raise ValueError("Recovery object is missing.")
    return root


def copy_checked(source, target, row):
    digest, size = hashlib.sha256(), 0
    while chunk := source.read(1024 * 1024):
        size += len(chunk)
        if size > row["size"]:
            raise ValueError("Recovery object grew.")
        digest.update(chunk)
        if target is not None:
            target.write(chunk)
    if size != row["size"] or digest.hexdigest() != row["sha256"]:
        raise ValueError("Recovery object integrity failed.")


def open_object(root, row):
    descriptor = os.open(root / row["key"], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    handle = os.fdopen(descriptor, "rb")
    info = os.fstat(handle.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != row["size"]:
        handle.close()
        raise ValueError("Unsafe recovery object handle.")
    return handle


def verify_objects(root, rows):
    rows = catalog(rows)
    root = scan(root, rows)
    for row in rows:
        with open_object(root, row) as source:
            copy_checked(source, None, row)
    return {"objects": len(rows), "bytes": sum(row["size"] for row in rows)}


def export_objects(root, rows, output):
    rows = catalog(rows)
    root = scan(root, rows)
    metadata = json.dumps({"format": FORMAT, "objects": rows}, sort_keys=True).encode()
    if len(metadata) > MAX_METADATA:
        raise ValueError("Recovery metadata limit exceeded.")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("objects.json", metadata)
        for row in rows:
            with open_object(root, row) as source, archive.open("objects/" + row["key"], "w") as target:
                copy_checked(source, target, row)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate recovery metadata key.")
        result[key] = value
    return result


def validate_archive(handle, expected=None):
    handle.seek(0, 2)
    if handle.tell() > MAX_ARCHIVE:
        raise ValueError("Recovery archive limit exceeded.")
    handle.seek(0)
    with zipfile.ZipFile(handle) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(infos) > MAX_OBJECTS + 1 or len(names) != len(set(names)):
            raise ValueError("Invalid recovery archive members.")
        for info in infos:
            mode = stat.S_IFMT(info.external_attr >> 16)
            if (info.compress_type != zipfile.ZIP_STORED or info.flag_bits & 1
                    or mode not in {0, stat.S_IFREG} or info.file_size < 0
                    or info.compress_size != info.file_size):
                raise ValueError("Unsafe recovery archive member.")
        metadata = archive.getinfo("objects.json")
        if metadata.file_size > MAX_METADATA:
            raise ValueError("Recovery metadata limit exceeded.")
        document = json.loads(archive.read(metadata), object_pairs_hook=unique_pairs)
        if not isinstance(document, dict) or set(document) != {"format", "objects"} or document["format"] != FORMAT:
            raise ValueError("Invalid recovery archive format.")
        rows = catalog(document["objects"])
        if set(names) != {"objects.json", *("objects/" + row["key"] for row in rows)}:
            raise ValueError("Unexpected recovery archive member.")
        if expected is not None and rows != catalog(expected):
            raise ValueError("Recovery archive and database disagree.")
        for row in rows:
            info = archive.getinfo("objects/" + row["key"])
            if info.file_size != row["size"]:
                raise ValueError("Recovery member size mismatch.")
            with archive.open(info) as source:
                copy_checked(source, None, row)
    return rows


def import_objects(handle, root, expected):
    rows = validate_archive(handle, expected)
    root = storage_root(root)
    with os.scandir(root) as entries:
        if next(entries, None) is not None:
            raise ValueError("Recovery destination must be empty.")
    handle.seek(0)
    with zipfile.ZipFile(handle) as archive:
        for row in rows:
            descriptor = os.open(root / row["key"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as target, archive.open("objects/" + row["key"]) as source:
                copy_checked(source, target, row)
                target.flush()
                os.fsync(target.fileno())
    return verify_objects(root, rows)
