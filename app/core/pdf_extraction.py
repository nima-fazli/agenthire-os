import asyncio
import hashlib
import os
import re
import signal
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from starlette.concurrency import run_in_threadpool

from app.core.config import Settings

TOOLS = {name: f"/usr/bin/{name}" for name in ("pdfinfo", "pdftotext", "prlimit")}


class ExtractionFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExtractedPdf:
    text: str
    page_count: int


class PdfExtractor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @staticmethod
    def ensure_tools() -> None:
        if os.name != "posix" or not all(
            Path(path).is_file() for path in TOOLS.values()
        ):
            raise ExtractionFailure("PDF_TOOLS_UNAVAILABLE")

    @staticmethod
    def _verify(handle: BinaryIO, expected_sha256: str) -> None:
        digest = hashlib.sha256()
        handle.seek(0)
        while chunk := handle.read(64 * 1024):
            digest.update(chunk)
        handle.seek(0)
        if digest.hexdigest() != expected_sha256:
            raise ExtractionFailure("PDF_INTEGRITY_MISMATCH")

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        async def drain() -> None:
            while await process.stdout.read(64 * 1024):
                pass

        await asyncio.gather(process.wait(), drain())

    async def _run(
        self, tool: str, handle: BinaryIO, args: list[str], *, limit: int
    ) -> bytes:
        handle.seek(0)
        settings = self._settings
        process = await asyncio.create_subprocess_exec(
            TOOLS["prlimit"],
            f"--as={settings.extraction_process_memory_mb * 1024 * 1024}",
            f"--cpu={settings.extraction_timeout_seconds}",
            "--core=0",
            "--",
            TOOLS[tool],
            *args,
            stdin=handle,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            env={"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        )
        output = bytearray()
        try:
            while chunk := await process.stdout.read(64 * 1024):
                if len(output) + len(chunk) > limit:
                    raise ExtractionFailure("PDF_TEXT_LIMIT")
                output.extend(chunk)
            return_code = await process.wait()
            if return_code:
                code = "PDF_RESOURCE_LIMIT" if return_code < 0 else "PDF_INVALID"
                raise ExtractionFailure(code)
            return bytes(output)
        finally:
            await self._terminate(process)

    async def extract(self, handle: BinaryIO, *, expected_sha256: str) -> ExtractedPdf:
        self.ensure_tools()
        try:
            async with asyncio.timeout(self._settings.extraction_timeout_seconds):
                await run_in_threadpool(self._verify, handle, expected_sha256)
                info = (
                    await self._run(
                        "pdfinfo", handle, ["-enc", "UTF-8", "-"], limit=64 * 1024
                    )
                ).decode("utf-8")
                pages = re.findall(r"^Pages:\s*([0-9]+)\s*$", info, re.MULTILINE)
                encrypted = re.findall(r"^Encrypted:\s*(yes|no)\b", info, re.MULTILINE)
                if not pages or int(pages[-1]) < 1:
                    raise ExtractionFailure("PDF_INVALID")
                if encrypted and encrypted[-1] == "yes":
                    raise ExtractionFailure("PDF_ENCRYPTED")
                page_count = int(pages[-1])
                if page_count > self._settings.extraction_max_pages:
                    raise ExtractionFailure("PDF_PAGE_LIMIT")
                raw = await self._run(
                    "pdftotext",
                    handle,
                    ["-enc", "UTF-8", "-eol", "unix", "-nopgbrk", "-", "-"],
                    limit=self._settings.extraction_max_text_bytes,
                )
                text = unicodedata.normalize(
                    "NFC", raw.decode("utf-8").replace("\x00", "")
                ).strip()
                if not text:
                    raise ExtractionFailure("PDF_NO_TEXT")
                if len(text.encode("utf-8")) > self._settings.extraction_max_text_bytes:
                    raise ExtractionFailure("PDF_TEXT_LIMIT")
                return ExtractedPdf(text, page_count)
        except TimeoutError as error:
            raise ExtractionFailure("PDF_TIMEOUT") from error
        except (UnicodeDecodeError, OSError) as error:
            raise ExtractionFailure("PDF_INVALID") from error
