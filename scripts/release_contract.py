"""Bind local release checks to accepted stage 5 and the complete current source."""

import hashlib
import json
import re
from pathlib import Path

from scripts.design_contract import MANIFEST as DESIGN_MANIFEST
from scripts.design_contract import digest
from scripts.source_bundle import LIMIT, _git, checked_path

BASE = "c22791a48278450905e3361557d37ca06bd53816"
MANIFEST = "scripts/fixtures/release_stage6_manifest.json"


def regular_file(root, name):
    checked_path(name)
    target = root / name
    if (not target.is_file() or not target.resolve().is_relative_to(root)
            or any(p.is_symlink() or p.is_junction() for p in (target, *target.parents))):
        raise ValueError("missing_or_unsafe_release_source: " + name)
    return target


def load_manifest(root):
    root = Path(root).resolve()
    value = json.loads(regular_file(root, MANIFEST).read_text(encoding="utf-8-sig"))
    if (not isinstance(value, dict) or set(value) != {"version", "base_commit", "files", "sha256"}
            or value["version"] != "release-stage-6-v1" or value["base_commit"] != BASE):
        raise ValueError("invalid_release_manifest")
    names, hashes = value["files"], value["sha256"]
    if (not isinstance(names, list) or not all(isinstance(n, str) for n in names)
            or not 3 <= len(names) <= 32 or len(names) != len(set(names)) or MANIFEST not in names
            or not isinstance(hashes, dict) or set(hashes) != set(names) - {MANIFEST}):
        raise ValueError("invalid_release_file_list")
    for name in names:
        path = regular_file(root, name)
        if name != MANIFEST and (not isinstance(hashes[name], str)
                or re.fullmatch(r"[0-9a-f]{64}", hashes[name]) is None or digest(path) != hashes[name]):
            raise ValueError("release_source_mismatch: " + name)
    return value


def fingerprint(root, names):
    root = Path(root).resolve()
    content = {name: digest(regular_file(root, name)) for name in sorted(names)}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def browser_fingerprint(root):
    """Match the existing browser runner's 17-file scope without reaccepting stage 5."""
    value = json.loads(regular_file(root, DESIGN_MANIFEST).read_text(encoding="utf-8-sig"))
    return fingerprint(root, value["feature_files"] + value["test_files"])


def source_snapshot(root, manifest):
    root = Path(root).resolve()

    def git(*args):
        return _git(root, *args).stdout.decode("utf-8").strip()

    def names(*args):
        return {n.decode("utf-8") for n in _git(root, *args).stdout.split(b"\0") if n}

    if Path(git("rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("release_repository_root_required")
    if git("branch", "--show-current") != "main" or git("merge-base", BASE, "HEAD") != BASE:
        raise ValueError("accepted_stage5_main_required")
    allowed = set(manifest["files"])
    changed = names("diff", "--name-only", "--no-renames", "-z", BASE, "--")
    untracked = names("ls-files", "--others", "--exclude-standard", "-z")
    if (changed | untracked) - allowed:
        raise ValueError("unrelated_release_source_changes")
    source = names("ls-tree", "-r", "--name-only", "-z", BASE) | allowed
    if sum(regular_file(root, name).stat().st_size for name in source) > LIMIT:
        raise ValueError("release_source_size_limit")
    return {"base_commit": BASE, "head_commit": git("rev-parse", "HEAD"),
            "working_tree_clean": not names("diff", "--name-only", "-z", "HEAD", "--") and not untracked,
            "file_count": len(source), "source_sha256": fingerprint(root, source)}
