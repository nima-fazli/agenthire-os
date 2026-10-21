import asyncio
from pathlib import Path
from threading import Event
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.health import router
from app.core.readiness import StorageProbe, expected_migration_heads
from app.services.runtime_health import ReadinessSnapshot, RuntimeReadiness

HEADS = frozenset({"0018_local_agents"})


def sessions(heads=HEADS, failure=None):
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(heads)
    session.execute.return_value = result
    if failure is not None:
        session.execute.side_effect = failure
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False
    return MagicMock(return_value=session), session


def test_expected_heads_come_from_packaged_migration_graph():
    assert expected_migration_heads() == HEADS


def test_storage_probe_writes_and_removes_only_its_own_file(tmp_path):
    existing = tmp_path / "keep.pdf"
    existing.write_bytes(b"private")
    assert asyncio.run(StorageProbe(tmp_path)())
    assert list(tmp_path.iterdir()) == [existing]
    assert existing.read_bytes() == b"private"


def test_storage_probe_refuses_missing_root_and_global_root(tmp_path):
    assert not asyncio.run(StorageProbe(tmp_path / "missing")())
    assert not asyncio.run(StorageProbe(Path(tmp_path.anchor))())


def test_storage_probe_rejects_linked_path_without_writing(tmp_path, monkeypatch):
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == tmp_path or original(path))
    assert not asyncio.run(StorageProbe(tmp_path)())
    assert not list(tmp_path.iterdir())


def test_storage_io_failure_is_unavailable_and_cleans_file(tmp_path, monkeypatch):
    import app.core.readiness as module

    def fail(*_):
        raise OSError("synthetic-private-path")

    monkeypatch.setattr(module.os, "fsync", fail)
    assert not asyncio.run(StorageProbe(tmp_path)())
    assert not list(tmp_path.iterdir())


def test_cancelled_storage_waiter_does_not_release_running_thread_slot(tmp_path, monkeypatch):
    probe = StorageProbe(tmp_path)
    entered, release = Event(), Event()
    original = probe._check

    def blocked():
        entered.set()
        assert release.wait(2)
        return original()

    monkeypatch.setattr(probe, "_check", blocked)

    async def run():
        task = asyncio.create_task(probe())
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not await StorageProbe(tmp_path)()
        finally:
            release.set()

    asyncio.run(run())
    assert asyncio.run(StorageProbe(tmp_path)())


@pytest.mark.parametrize("heads", [HEADS, frozenset(), frozenset({"stale"})], ids=["head", "empty", "stale"])
def test_readiness_checks_actual_migration_heads(heads):
    factory, session = sessions(heads)
    probe = RuntimeReadiness(factory, AsyncMock(return_value=True), HEADS)

    async def run():
        try:
            return await probe.snapshot()
        finally:
            await probe.close()

    result = asyncio.run(run())
    assert result.ready is (heads == HEADS)
    assert result.schema == ("ok" if heads == HEADS else "mismatch")
    session.__aexit__.assert_awaited_once()
    session.commit.assert_not_called()


def test_database_failure_does_not_hide_storage_result_or_leak_detail():
    failure = OperationalError("private SQL", {}, RuntimeError("private password"))
    factory, _ = sessions(failure=failure)
    probe = RuntimeReadiness(factory, AsyncMock(return_value=True), HEADS)

    async def run():
        try:
            return await probe.snapshot()
        finally:
            await probe.close()

    result = asyncio.run(run())
    assert not result.ready and result.storage == "ok"
    assert result.operator_report() == {"database": "unavailable", "schema": "unknown", "storage": "ok"}


def test_readiness_coalesces_concurrent_clients_and_caches_completed_probe():
    factory, _ = sessions()
    storage = AsyncMock(return_value=True)
    probe = RuntimeReadiness(factory, storage, HEADS)

    async def run():
        result = await asyncio.gather(*(probe.snapshot() for _ in range(20)))
        assert all(item.ready for item in result)
        assert (await probe.snapshot()).ready
        await probe.close()

    asyncio.run(run())
    assert storage.await_count == 1 and factory.call_count == 1


def test_cancelled_client_does_not_cancel_shared_probe():
    factory, _ = sessions()

    async def run():
        gate = asyncio.Event()

        async def storage():
            await gate.wait()
            return True

        probe = RuntimeReadiness(factory, storage, HEADS)
        first = asyncio.create_task(probe.snapshot())
        second = asyncio.create_task(probe.snapshot())
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        gate.set()
        assert (await second).ready
        await probe.close()
        assert not (await probe.snapshot()).ready

    asyncio.run(run())


def test_probe_timeout_and_unexpected_failure_are_not_ready():
    factory, _ = sessions()

    async def run():
        async def slow():
            await asyncio.Event().wait()

        probe = RuntimeReadiness(factory, slow, HEADS, timeout=0.01)
        assert not (await probe.snapshot()).ready
        await probe.close()
        failing = RuntimeReadiness(factory, AsyncMock(side_effect=RuntimeError("private")), HEADS)
        assert not (await failing.snapshot()).ready
        await failing.close()

    asyncio.run(run())


def test_cache_expiry_rechecks_and_shutdown_cancels_owned_probe():
    factory, _ = sessions()

    async def run():
        storage = AsyncMock(return_value=True)
        probe = RuntimeReadiness(factory, storage, HEADS, cache_seconds=0)
        assert (await probe.snapshot()).ready
        assert (await probe.snapshot()).ready
        assert storage.await_count == 2
        await probe.close()
        blocked = RuntimeReadiness(factory, AsyncMock(side_effect=lambda: None), HEADS)

        async def slow():
            await asyncio.Event().wait()

        blocked._storage = slow
        waiter = asyncio.create_task(blocked.snapshot())
        await asyncio.sleep(0)
        await blocked.close()
        with pytest.raises(asyncio.CancelledError):
            await waiter

    asyncio.run(run())


@pytest.mark.parametrize("snapshot,code", [
    (ReadinessSnapshot("ok", "ok", "ok"), 200),
    (ReadinessSnapshot("unavailable", "unknown", "ok"), 503),
    (ReadinessSnapshot("ok", "mismatch", "ok"), 503),
    (ReadinessSnapshot("ok", "ok", "unavailable"), 503),
], ids=["ready", "database", "schema", "storage"])
def test_public_readiness_is_minimal_and_liveness_is_independent(snapshot, code):
    application = FastAPI()
    application.include_router(router)
    application.state.readiness = MagicMock()
    application.state.readiness.snapshot = AsyncMock(return_value=snapshot)
    client = TestClient(application)
    response = client.get("/ready")
    assert response.status_code == code
    assert response.json() == {"status": "ready" if code == 200 else "not_ready"}
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/health").status_code == 200
    assert application.state.readiness.snapshot.await_count == 1


def test_uninitialized_readiness_fails_closed():
    application = FastAPI()
    application.include_router(router)
    assert TestClient(application).get("/ready").status_code == 503
