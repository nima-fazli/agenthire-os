"""Private, bounded local backup store; no encryption or offsite transport."""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.core.recovery_archive import MAX_ARCHIVE, unique_pairs, validate_archive

FORMAT = "agenthire-private-backup-v1"
COMPONENTS = {"database.dump": 256 * 1024 * 1024, "documents.zip": MAX_ARCHIVE,
              "source.env": 65536, "database.json": 512 * 1024, "state.json": 2048}
IDENTITY = re.compile(r"backup-[0-9]{8}T[0-9]{12}Z-[0-9a-f]{32}")
ACL = r'''
$ErrorActionPreference = 'Stop'
$path = $env:AGENTHIRE_PRIVATE_STORE
$user = [Security.Principal.WindowsIdentity]::GetCurrent().User
$system = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
if ($env:AGENTHIRE_PRIVATE_INIT -eq '1') {
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($user)
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @($user, $system)) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $path -AclObject $acl
}
$items = @((Get-Item -LiteralPath $path -Force)) + @(Get-ChildItem -LiteralPath $path -Force -Recurse)
foreach ($item in $items) {
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Unsafe path.' }
    $acl = Get-Acl -LiteralPath $item.FullName
    $owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ($owner -notin @($user.Value, 'S-1-5-32-544')) { throw 'Owner mismatch.' }
    if ($item.FullName -eq $path -and $owner -ne $user.Value) { throw 'Root owner mismatch.' }
    if ($item.FullName -eq $path -and -not $acl.AreAccessRulesProtected) { throw 'Inherited root access.' }
    $own = $false
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq 'Allow') {
            if ($rule.IdentityReference.Value -notin @($user.Value, $system.Value)) { throw 'Foreign access.' }
            if ($rule.IdentityReference.Value -eq $user.Value -and
                ($rule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -eq
                [Security.AccessControl.FileSystemRights]::FullControl) { $own = $true }
        }
    }
    if (-not $own) { throw 'Owner control missing.' }
}
[Console]::Write('private')
'''


def safe_path(path):
    path = Path(os.path.abspath(path))
    if path == Path(path.anchor) or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError("Unsafe backup path.")
    return path


def private_directory(path, *, initialize=False, runner=subprocess.run):
    path = safe_path(path)
    if not path.is_dir():
        raise ValueError("Backup directory unavailable.")
    if os.name == "nt":
        # A Python child of pwsh inherits PS7 modules that powershell.exe cannot load.
        environment = {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}
        environment.update(AGENTHIRE_PRIVATE_STORE=str(path),
                           AGENTHIRE_PRIVATE_INIT="1" if initialize else "0")
        result = runner(("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ACL),
                        env=environment, capture_output=True, text=True, timeout=30, check=False)
        if result.returncode or result.stdout != "private":
            raise ValueError("Private Windows ACL required.")
    else:
        if initialize:
            path.chmod(0o700)
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Private owner-only directory required.")
    return path


def open_private(path, mode="rb"):
    path = safe_path(path)
    flags = os.O_RDONLY if mode == "rb" else os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o600)
    handle = os.fdopen(descriptor, mode)
    info = os.fstat(handle.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        handle.close()
        raise ValueError("Unsafe backup file.")
    return handle


def write_json(path, value):
    with open_private(path, "wb") as handle:
        handle.write(json.dumps(value, sort_keys=True).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_json(path, limit=512 * 1024):
    with open_private(path) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Backup metadata limit exceeded.")
    value = json.loads(data, object_pairs_hook=unique_pairs)
    if not isinstance(value, dict):
        raise TypeError("Backup metadata object required.")
    return value


def file_digest(path, limit):
    with open_private(path) as handle:
        before = os.fstat(handle.fileno())
        size = before.st_size
        if not 1 <= size <= limit:
            raise ValueError("Backup component limit exceeded.")
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
        after = os.fstat(handle.fileno())
        if after.st_size != size or after.st_mtime_ns != before.st_mtime_ns or after.st_nlink != 1:
            raise ValueError("Backup component changed.")
    return {"size": size, "sha256": digest}


class BackupStore:
    def __init__(self, path, repository):
        self.root, repository = safe_path(path), safe_path(repository)
        if self.root == repository or repository in self.root.parents or self.root in repository.parents:
            raise ValueError("Backup store must be separate from the repository.")

    def initialize(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
        private_directory(self.root, initialize=True)
        write_json(self.root / "store.json", {"format": FORMAT, "store_id": uuid4().hex})
        with open_private(self.root / "store.lock", "wb") as handle:
            handle.write(b"0")
        (self.root / "receipts").mkdir(mode=0o700)
        return self.check()

    def check(self):
        private_directory(self.root)
        marker = read_json(self.root / "store.json", 1024)
        if (set(marker) != {"format", "store_id"} or marker["format"] != FORMAT
                or not re.fullmatch(r"[0-9a-f]{32}", marker["store_id"])):
            raise ValueError("Invalid private backup store.")
        entries = list(self.root.iterdir())
        if len(entries) > 205:
            raise ValueError("Backup inventory limit exceeded.")
        for path in entries:
            safe_path(path)
            if path.name not in {"store.json", "store.lock", "receipts", "journal.json"}:
                name = path.name.removesuffix(".partial")
                if not IDENTITY.fullmatch(name) or not path.is_dir():
                    raise ValueError("Unexpected backup store entry.")
        if not (self.root / "receipts").is_dir():
            raise ValueError("Backup receipts unavailable.")
        return marker["store_id"]

    @contextmanager
    def locked(self):
        self.check()
        with (self.root / "store.lock").open("r+b") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != 1:
                raise ValueError("Unsafe backup lock.")
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def new(self, *, source_kind, revision):
        if source_kind not in {"normal", "synthetic"} or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Invalid backup provenance.")
        if (self.root / "journal.json").exists():
            raise ValueError("Resume the recorded source first.")
        if shutil.disk_usage(self.root).free < 2 * 1024**3:
            raise ValueError("Insufficient backup free space.")
        identity = "backup-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ-") + uuid4().hex
        directory = self.root / (identity + ".partial")
        directory.mkdir(mode=0o700)
        write_json(directory / "state.json", {"store_id": self.check(), "backup_id": identity,
                                            "source_kind": source_kind, "revision": revision})
        return identity, directory

    def seal(self, identity):
        directory = self.root / (identity + ".partial")
        if {p.name for p in directory.iterdir()} != set(COMPONENTS):
            raise ValueError("Incomplete backup components.")
        with open_private(directory / "database.dump") as handle:
            if handle.read(5) != b"PGDMP":
                raise ValueError("PostgreSQL custom dump required.")
        with open_private(directory / "documents.zip") as handle:
            validate_archive(handle)
        manifest = {"format": FORMAT, "store_id": self.check(), "backup_id": identity,
                    "files": {name: file_digest(directory / name, limit) for name, limit in COMPONENTS.items()}}
        write_json(directory / "backup.json", manifest)
        self.verify(identity, partial=True)
        if (self.root / identity).exists():
            raise ValueError("Backup identity already exists.")
        directory.rename(self.root / identity)
        return self.verify(identity)

    def verify(self, identity, *, partial=False):
        if not isinstance(identity, str) or not IDENTITY.fullmatch(identity):
            raise ValueError("Invalid backup identity.")
        directory = safe_path(self.root / (identity + (".partial" if partial else "")))
        if {p.name for p in directory.iterdir()} != {*COMPONENTS, "backup.json"}:
            raise ValueError("Unexpected backup components.")
        manifest = read_json(directory / "backup.json", 8192)
        if (set(manifest) != {"format", "store_id", "backup_id", "files"}
                or manifest["format"] != FORMAT or manifest["store_id"] != self.check()
                or manifest["backup_id"] != identity or set(manifest["files"]) != set(COMPONENTS)):
            raise ValueError("Backup manifest mismatch.")
        for name, limit in COMPONENTS.items():
            if file_digest(directory / name, limit) != manifest["files"][name]:
                raise ValueError("Backup integrity failed.")
        state = read_json(directory / "state.json", 2048)
        if state.get("store_id") != manifest["store_id"] or state.get("backup_id") != identity:
            raise ValueError("Backup ownership mismatch.")
        with open_private(directory / "documents.zip") as handle:
            validate_archive(handle)
        return manifest

    def inventories(self):
        self.check()
        return sorted(path.name for path in self.root.iterdir() if IDENTITY.fullmatch(path.name))

    def receipt(self, identity):
        manifest = self.verify(identity)
        value = {"status": "passed", "backup_id": identity,
                 "manifest": file_digest(self.root / identity / "backup.json", 8192),
                 "store_id": manifest["store_id"]}
        write_json(self.root / "receipts" / (identity + "-" + uuid4().hex + ".json"), value)

    def prune(self, keep, *, execute=False):
        if type(keep) is not int or not 2 <= keep <= 20:
            raise ValueError("Keep between 2 and 20 complete backups.")
        identities = self.inventories()
        if (self.root / "journal.json").exists() or any(p.name.endswith(".partial") for p in self.root.iterdir()):
            raise ValueError("Resolve interrupted capture before retention.")
        manifests = {identity: self.verify(identity) for identity in identities}
        removed, retained = identities[:-keep], identities[-keep:]
        verified = False
        for identity in retained:
            for path in (self.root / "receipts").glob(identity + "-*.json"):
                receipt = read_json(path, 2048)
                if receipt == {"status": "passed", "backup_id": identity,
                               "manifest": file_digest(self.root / identity / "backup.json", 8192),
                               "store_id": manifests[identity]["store_id"]}:
                    verified = True
        if removed and not verified:
            raise ValueError("A retained backup must pass isolated restore before pruning.")
        if execute:
            for identity in removed:
                shutil.rmtree(self.root / identity)
        return {"remove": removed, "retain": retained, "executed": execute}
