import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.workers import document_extraction as worker


def test_healthcheck_requires_a_fresh_valid_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "heartbeat"
    settings = Settings(_env_file=None)
    monkeypatch.setattr(worker.time, "monotonic", lambda: 1000)
    assert not worker.healthy(settings, path)
    worker.heartbeat(path)
    assert worker.healthy(settings, path)
    path.write_text("800", encoding="ascii")
    assert not worker.healthy(settings, path)
    path.write_text("invalid", encoding="ascii")
    assert not worker.healthy(settings, path)


def test_worker_processes_then_stops_without_polling_again(tmp_path: Path) -> None:
    async def run():
        stop = asyncio.Event()
        processor = AsyncMock()

        async def process():
            stop.set()
            return True

        processor.run_one.side_effect = process
        await worker.run_worker(
            processor, Settings(_env_file=None), stop, tmp_path / "heartbeat"
        )
        processor.run_one.assert_awaited_once()

    asyncio.run(run())


def test_idle_worker_can_stop_during_poll(tmp_path: Path) -> None:
    async def run():
        stop = asyncio.Event()
        processor = AsyncMock()
        processor.run_one.return_value = False
        task = asyncio.create_task(
            worker.run_worker(
                processor, Settings(_env_file=None), stop, tmp_path / "heartbeat"
            )
        )
        await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        processor.run_one.assert_awaited_once()

    asyncio.run(run())


def test_worker_survives_transient_processing_error(tmp_path: Path) -> None:
    async def run():
        stop = asyncio.Event()
        processor = AsyncMock()
        calls = 0

        async def process():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary failure")
            stop.set()
            return True

        processor.run_one.side_effect = process
        settings = Settings(_env_file=None, extraction_poll_seconds=0.1)
        await asyncio.wait_for(
            worker.run_worker(processor, settings, stop, tmp_path / "heartbeat"),
            timeout=1,
        )
        assert calls == 2

    asyncio.run(run())
