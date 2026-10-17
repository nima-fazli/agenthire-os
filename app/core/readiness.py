import asyncio
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from threading import Lock

from alembic.script import ScriptDirectory

# A timed-out caller must not create an unbounded queue of filesystem threads.
_STORAGE_SLOT = Lock()


@lru_cache(maxsize=1)
def expected_migration_heads() -> frozenset[str]:
    migrations = Path(__file__).resolve().parents[2] / "migrations"
    heads = frozenset(ScriptDirectory(str(migrations)).get_heads())
    if not heads:
        raise RuntimeError("Migration metadata is unavailable.")
    return heads


class StorageProbe:
    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.abspath(root))

    def _check(self) -> bool:
        root = self.root
        if root == Path(root.anchor) or any(
            item.is_symlink() for item in (root, *root.parents)
        ):
            return False
        if not root.is_dir():
            return False
        name = None
        try:
            descriptor, name = tempfile.mkstemp(prefix=".readiness-", dir=root)
            with os.fdopen(descriptor, "wb") as output:
                output.write(b"1")
                output.flush()
                os.fsync(output.fileno())
            return True
        finally:
            if name is not None:
                Path(name).unlink(missing_ok=True)

    def _run(self) -> bool:
        try:
            return self._check()
        except OSError:
            return False
        finally:
            _STORAGE_SLOT.release()

    async def __call__(self) -> bool:
        if not _STORAGE_SLOT.acquire(blocking=False):
            return False
        try:
            future = asyncio.get_running_loop().run_in_executor(None, self._run)
        except BaseException:
            _STORAGE_SLOT.release()
            raise
        future.add_done_callback(
            lambda done: done.exception() if not done.cancelled() else None
        )
        # Cancellation releases the waiter, never the running thread's slot.
        return await asyncio.shield(future)
