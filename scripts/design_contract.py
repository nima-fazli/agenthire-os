"""Verify the bounded stage 5 source delivery without importing the application."""

import hashlib
import json
from pathlib import Path, PurePosixPath

BASE = "160fc05fe506caf47da0dcdbca525a0e5df93de5"
MANIFEST = "scripts/fixtures/design_stage5_manifest.json"


def digest(path):
    raw = Path(path).read_bytes()
    return hashlib.sha256(raw.removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")).hexdigest()


def load_manifest(root):
    root = Path(root).resolve()
    value = json.loads((root / MANIFEST).read_text(encoding="utf-8-sig"))
    if value.get("version") != "design-stage-5-v1" or value.get("base_commit") != BASE:
        raise ValueError("invalid_design_manifest")
    paths = value["feature_files"] + value["test_files"]
    if (not 5 <= len(paths) <= 32 or len(paths) != len(set(paths)) or MANIFEST not in paths
            or set(value["sha256"]) != set(paths) - {MANIFEST}):
        raise ValueError("invalid_design_file_list")
    for name in paths:
        path = PurePosixPath(name)
        if (not name or "\\" in name or ":" in name or path.is_absolute()
                or ".." in path.parts or str(path) != name):
            raise ValueError("unsafe_design_source")
        target = root / name
        if (not target.is_file() or not target.resolve().is_relative_to(root)
                or any(p.is_symlink() or p.is_junction() for p in (target, *target.parents))):
            raise ValueError("missing_or_unsafe_design_source: " + name)
        if name != MANIFEST and digest(target) != value["sha256"][name]:
            raise ValueError("design_source_mismatch: " + name)
    return value


def source_digest(root):
    manifest = load_manifest(root)
    content = {name: digest(Path(root) / name) for name in sorted(
        manifest["feature_files"] + manifest["test_files"])}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    value = load_manifest(root)
    print(json.dumps({"status": "verified", "stage": 5, "source_sha256": source_digest(root),
                      "files": len(value["feature_files"]) + len(value["test_files"])}))
