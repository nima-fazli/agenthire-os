import argparse
import asyncio
import logging
import signal
import tempfile
import time
from pathlib import Path

HEARTBEAT = Path(tempfile.gettempdir()) / "agenthire-embedding.heartbeat"
HEARTBEAT_INTERVAL_SECONDS = 5
HEARTBEAT_MAX_AGE_SECONDS = 90
logger = logging.getLogger("agenthire.embeddings.worker")


def heartbeat(path: Path = HEARTBEAT) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(str(time.monotonic()), encoding="ascii")
    temporary.replace(path)


def healthy(path: Path = HEARTBEAT) -> bool:
    try:
        age = time.monotonic() - float(path.read_text(encoding="ascii"))
        return 0 <= age <= HEARTBEAT_MAX_AGE_SECONDS
    except (OSError, ValueError):
        return False


async def run_worker(processor, settings, stop, path: Path = HEARTBEAT) -> None:
    async def pulse():
        while not stop.is_set():
            heartbeat(path)
            try:
                await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)
            except TimeoutError:
                pass

    async def consume():
        while not stop.is_set():
            try:
                processed = await processor.run_one()
            except Exception:
                logger.exception("embedding_worker_error")
                processed = False
            if not processed:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.extraction_poll_seconds)
                except TimeoutError:
                    pass

    async with asyncio.TaskGroup() as group:
        group.create_task(pulse())
        consumer = group.create_task(consume())
        await stop.wait()
        consumer.cancel()


async def main_loop(settings) -> None:
    from app.core.local_embeddings import LocalEmbeddingEncoder
    from app.db.session import async_session_factory, engine
    from app.services.document_embeddings import EmbeddingProcessor

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    encoder = LocalEmbeddingEncoder(settings.embedding_base_url, timeout_seconds=settings.embedding_timeout_seconds)
    processor = EmbeddingProcessor(async_session_factory, encoder, settings)
    try:
        await run_worker(processor, settings, stop)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        raise SystemExit(0 if healthy() else 1)

    from app.core.config import get_settings
    from app.core.logging import configure_logging

    settings = get_settings()
    if not settings.semantic_enabled:
        raise SystemExit("Enable local semantic processing before starting the worker.")
    configure_logging(level=settings.log_level)
    asyncio.run(main_loop(settings))


if __name__ == "__main__":
    main()
