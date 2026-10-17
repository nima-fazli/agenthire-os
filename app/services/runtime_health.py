import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

from sqlalchemy.exc import SQLAlchemyError

from app.repositories.runtime_health import RuntimeHealthRepository

logger = logging.getLogger("agenthire.readiness")


@dataclass(frozen=True)
class ReadinessSnapshot:
    database: str = "unavailable"
    schema: str = "unknown"
    storage: str = "unavailable"

    @property
    def ready(self) -> bool:
        return (self.database, self.schema, self.storage) == ("ok", "ok", "ok")

    def operator_report(self) -> dict[str, str]:
        return asdict(self)


class RuntimeReadiness:
    def __init__(
        self, session_factory, storage_probe: Callable[[], Awaitable[bool]],
        expected_heads: frozenset[str], *, timeout: float = 2.0,
        cache_seconds: float = 1.0,
    ) -> None:
        if not expected_heads:
            raise ValueError("Expected migration heads are required.")
        self._sessions = session_factory
        self._storage = storage_probe
        self._expected = expected_heads
        self._timeout = timeout
        self._cache_seconds = cache_seconds
        self._task: asyncio.Task | None = None
        self._finished = 0.0
        self._closed = False

    async def _probe(self) -> ReadinessSnapshot:
        components = {"database": "unavailable", "schema": "unknown", "storage": "unavailable"}

        async def database() -> None:
            try:
                async with self._sessions() as session:
                    repository = RuntimeHealthRepository(session)
                    await repository.configure()
                    actual = await repository.migration_heads()
                components["database"] = "ok"
                components["schema"] = "ok" if actual == self._expected else "mismatch"
            except (SQLAlchemyError, OSError, TimeoutError):
                pass

        async def storage() -> None:
            try:
                if await self._storage():
                    components["storage"] = "ok"
            except OSError:
                pass

        try:
            async with asyncio.timeout(self._timeout):
                async with asyncio.TaskGroup() as group:
                    group.create_task(database())
                    group.create_task(storage())
        except TimeoutError:
            components = {"database": "unavailable", "schema": "unknown", "storage": "unavailable"}
        except Exception:
            logger.exception("readiness_probe_failed")
            components = {"database": "unavailable", "schema": "unknown", "storage": "unavailable"}
        self._finished = time.monotonic()
        return ReadinessSnapshot(**components)

    async def snapshot(self) -> ReadinessSnapshot:
        if self._closed:
            return ReadinessSnapshot()
        if self._task is None or (
            self._task.done() and time.monotonic() - self._finished >= self._cache_seconds
        ):
            self._task = asyncio.create_task(self._probe())
        # Concurrent probes coalesce. A disconnected client does not cancel others.
        return await asyncio.shield(self._task)

    async def close(self) -> None:
        self._closed = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
