from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio

    from app.core.config import Settings
    from app.services.document_extraction import ExtractionProcessor

HEARTBEAT = Path(tempfile.gettempdir()) / "agenthire-extraction.heartbeat"


def heartbeat(path: Path = HEARTBEAT) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(str(time.monotonic()), encoding="ascii")
    temporary.replace(path)


def healthy(settings: Settings, path: Path = HEARTBEAT) -> bool:
    try:
        age = time.monotonic() - float(path.read_text(encoding="ascii"))
        return 0 <= age <= max(90, settings.extraction_timeout_seconds + 30)
    except (OSError, ValueError):
        return False


async def run_worker(
    processor: ExtractionProcessor,
    settings: Settings,
    stop: asyncio.Event,
    path: Path = HEARTBEAT,
) -> None:
    import asyncio
    import logging

    logger = logging.getLogger("agenthire.extraction.worker")
    while not stop.is_set():
        heartbeat(path)
        try:
            processed = await processor.run_one()
        except Exception:
            logger.exception("document_extraction_worker_error")
            processed = False
        if not processed:
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=settings.extraction_poll_seconds
                )
            except TimeoutError:
                pass


async def main_loop(settings: Settings) -> None:
    import asyncio
    import signal

    from app.core.document_storage import LocalDocumentStorage
    from app.core.pdf_extraction import PdfExtractor
    from app.db.session import async_session_factory, engine
    from app.services.document_extraction import ExtractionProcessor

    PdfExtractor.ensure_tools()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    processor = ExtractionProcessor(
        async_session_factory,
        LocalDocumentStorage(settings.document_storage_path),
        PdfExtractor(settings),
        settings,
    )
    try:
        await run_worker(processor, settings, stop)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()

    from app.core.config import get_settings

    settings = get_settings()
    if args.healthcheck:
        raise SystemExit(0 if healthy(settings) else 1)

    import asyncio

    from app.core.logging import configure_logging

    configure_logging(level=settings.log_level)
    asyncio.run(main_loop(settings))


if __name__ == "__main__":
    main()
