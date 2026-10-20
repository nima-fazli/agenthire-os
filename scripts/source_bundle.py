"""Plan or export a clean committed source tree; never collect working files."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

PREFIX = "agenthire-os/"
MANIFEST = PREFIX + "SOURCE_MANIFEST.json"
LIMIT = 50 * 1024 * 1024
ROOT_FILES = frozenset({
    ".dockerignore", ".env.example", ".gitignore", ".gitattributes", "AGENTS.md",
    "alembic.ini", "compose.yaml", "compose.ci.yaml", "compose.quality.yaml", "Dockerfile",
    "pyproject.toml", "uv.lock", "README.md", "LICENSE", "LICENSE.md", "NOTICE", "CHANGELOG.md",
})
SOURCE_DIRS = frozenset({"app", "docs", "migrations", "scripts", "tests", ".github"})
REQUIRED = frozenset({
    "pyproject.toml", "uv.lock", "README.md", "Dockerfile", "compose.yaml", "compose.ci.yaml",
    "alembic.ini", "app/main.py", ".github/workflows/verify.yml", ".github/dependabot.yml",
})


class BundleError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def checked_path(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in path.parts)
            or "\\" in value or ":" in value or any(ord(c) < 32 for c in value)):
        raise BundleError("invalid_tracked_path")
    names = [part.lower() for part in path.parts]
    if (any(part in {".git", ".venv", "storage", "__pycache__"} for part in names)
            or any(part.startswith(".env") and part != ".env.example" for part in names)
            or path.suffix.lower() in {".pdf", ".docx", ".zip", ".pyc", ".pyo", ".log", ".pem", ".key"}
            or path.name.lower().startswith(("agenthire_os_recovery", "agenthire_os_project_recovery", "agenthire_os_step"))
            or path.name.lower() in {"source.env", "secrets.json", "credentials.json"}):
        raise BundleError("private_tracked_file")
    if (len(path.parts) == 1 and value not in ROOT_FILES
            or len(path.parts) > 1 and path.parts[0] not in SOURCE_DIRS):
        raise BundleError("unsupported_source_path")
    return value


def _git(root: Path, *arguments: str, allowed=(0,)):
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_NO_REPLACE_OBJECTS="1", GIT_OPTIONAL_LOCKS="0")
    result = subprocess.run(
        ("git", "--no-pager", "-c", "core.fsmonitor=false", "-C", str(root), *arguments),
        env=environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False,
    )
    if result.returncode not in allowed:
        raise BundleError("git_source_inspection_failed")
    return result


def inspect_source(root: Path):
    root = root.resolve()
    actual = Path(_git(root, "rev-parse", "--show-toplevel").stdout.decode().strip()).resolve()
    if actual != root:
        raise BundleError("repository_root_required")
    head = _git(root, "rev-parse", "HEAD").stdout.decode().strip()
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head):
        raise BundleError("invalid_commit_identity")
    entries = _git(root, "ls-tree", "-r", "-z", "HEAD").stdout.split(b"\0")
    files = []
    for entry in filter(None, entries):
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, _ = metadata.split()
        if kind != b"blob" or mode not in {b"100644", b"100755"}:
            raise BundleError("source_links_or_submodules_rejected")
        files.append(checked_path(raw_name.decode("utf-8")))
    if len(files) != len(set(files)) or not REQUIRED.issubset(files):
        raise BundleError("incomplete_committed_tree")
    project = tomllib.loads(_git(root, "show", "HEAD:pyproject.toml").stdout.decode("utf-8"))
    if project.get("project", {}).get("name") != "agenthire-os":
        raise BundleError("project_mismatch")
    clean = _git(root, "diff", "--quiet", "--no-ext-diff", "HEAD", "--", allowed=(0, 1)).returncode == 0
    return root, head, tuple(sorted(files)), clean


def add_manifest(path: Path, head: str, files: tuple[str, ...]):
    with zipfile.ZipFile(path, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if (len(members) != len(files) or {item.filename for item in members} != {PREFIX + n for n in files}
                or sum(item.file_size for item in members) > LIMIT):
            raise BundleError("archive_content_mismatch_or_size_limit")
        hashes = {name: hashlib.sha256(archive.read(PREFIX + name)).hexdigest() for name in files}
        value = {"version": "source-bundle-v1", "project": "agenthire-os", "commit": head,
                 "files": hashes, "file_count": len(files)}
        entry = zipfile.ZipInfo(MANIFEST, date_time=(1980, 1, 1, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = 0o100644 << 16
        archive.writestr(entry, json.dumps(value, sort_keys=True, indent=2).encode())


def bundle(root: Path, output: Path | None = None, *, execute=False):
    root, head, files, clean = inspect_source(root)
    output = (output or root.parent / f"agenthire-os-source-{head[:12]}.zip").absolute()
    if output.resolve().is_relative_to(root) or output.suffix.lower() != ".zip":
        raise BundleError("output_path_rejected")
    result = {"version": "source-bundle-v1", "status": "plan", "commit": head,
              "file_count": len(files), "working_tree_clean": clean, "output": str(output), "executed": False}
    if not execute:
        return result
    if not clean:
        raise BundleError("uncommitted_source_changes")
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise BundleError("output_exists_or_parent_missing")
    descriptor, temporary = tempfile.mkstemp(prefix=".agenthire-source-", suffix=".zip", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary)
    try:
        _git(root, "archive", "--format=zip", "--prefix=" + PREFIX, "--output=" + str(temporary), head)
        if temporary.stat().st_size > LIMIT:
            raise BundleError("source_size_limit")
        add_manifest(temporary, head, files)
        # Same-directory hard linking publishes exclusively; existing output
        # files are never replaced, including a concurrent creator's file.
        os.link(temporary, output)
        result.update(status="created", executed=True,
                      sha256=hashlib.sha256(temporary.read_bytes()).hexdigest())
        return result
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(bundle(Path.cwd(), args.output, execute=args.execute), sort_keys=True))
        return 0
    except BundleError as error:
        print(json.dumps({"status": "failed", "diagnostic": error.code}))
        return 2
    except (OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile):
        print(json.dumps({"status": "failed", "diagnostic": "source_bundle_io_or_metadata_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
