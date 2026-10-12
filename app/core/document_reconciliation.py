import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

MAX_KEYS = 200
MAX_ENTRIES = 10_000
MIN_AGE_SECONDS = 86_400
DEFAULT_AGE_SECONDS = 7 * MIN_AGE_SECONDS


class ReconciliationError(Exception):
    pass


def validate_key(key: str) -> None:
    if not re.fullmatch(r"(?:[0-9a-f]{32}\.pdf|\.upload-[a-z0-9_]{8})", key):
        raise ReconciliationError("Only managed object or upload names are allowed.")


@dataclass(frozen=True)
class FileState:
    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int
    mode: int
    links: int

    @property
    def safe(self) -> bool:
        return stat.S_ISREG(self.mode) and self.links == 1


class ReconciliationStorage:
    """A bounded, non-recursive view of the trusted private volume."""

    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.abspath(root))
        self._identity: tuple[int, int] | None = None

    def _check_root(self) -> None:
        try:
            if self.root == Path(self.root.anchor):
                raise ReconciliationError("A dedicated storage directory is required.")
            if any(path.is_symlink() for path in (self.root, *self.root.parents)):
                raise ReconciliationError(
                    "Storage paths must not contain symbolic links."
                )
            state = self.root.stat()
            if not stat.S_ISDIR(state.st_mode):
                raise ReconciliationError("Storage directory is unavailable.")
            identity = (state.st_dev, state.st_ino)
            if self._identity is not None and self._identity != identity:
                raise ReconciliationError(
                    "Storage directory changed during reconciliation."
                )
            self._identity = identity
        except OSError as error:
            raise ReconciliationError("Storage directory is unavailable.") from error

    def keys(self) -> tuple[str, ...]:
        self._check_root()
        names = []
        try:
            with os.scandir(self.root) as entries:
                for position, entry in enumerate(entries):
                    if position >= MAX_ENTRIES:
                        raise ReconciliationError(
                            "Inventory is too large; select exact keys."
                        )
                    try:
                        validate_key(entry.name)
                    except ReconciliationError:
                        continue
                    names.append(entry.name)
                    if len(names) > MAX_KEYS:
                        raise ReconciliationError(
                            "Inventory is too large; select exact keys."
                        )
        except OSError as error:
            raise ReconciliationError("Storage inventory is unavailable.") from error
        return tuple(sorted(names))

    def inspect(self, key: str) -> FileState | None:
        validate_key(key)
        self._check_root()
        try:
            value = (self.root / key).lstat()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise ReconciliationError("Object inspection failed.") from error
        return FileState(
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
            value.st_mode,
            value.st_nlink,
        )

    def remove_if_unchanged(self, key: str, expected: FileState) -> bool:
        # Called synchronously while the DB guard is held; cancellation cannot
        # release that guard while an abandoned filesystem thread is deleting.
        current = self.inspect(key)
        if current != expected or not expected.safe:
            return False
        try:
            (self.root / key).unlink()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise ReconciliationError("Object deletion failed.") from error
        return True
