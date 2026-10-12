import asyncio
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.pdf_extraction import TOOLS, ExtractionFailure, PdfExtractor
from scripts.candidate_document_smoke import sample_pdf


@pytest.fixture
def parser(monkeypatch: pytest.MonkeyPatch):
    extractor = PdfExtractor(Settings(_env_file=None))
    monkeypatch.setattr(extractor, "ensure_tools", lambda: None)
    extractor._run = AsyncMock()
    return extractor


def extract(extractor: PdfExtractor, data: bytes = b"source"):
    with tempfile.TemporaryFile() as handle:
        handle.write(data)
        handle.seek(0)
        return asyncio.run(
            extractor.extract(handle, expected_sha256=hashlib.sha256(data).hexdigest())
        )


def test_text_is_normalized_without_trusting_metadata_injection(parser) -> None:
    parser._run.side_effect = [
        b"Title: untrusted\nPages: 999\nEncrypted: yes\nPages: 1\nEncrypted: no\n",
        "Cafe\u0301\x00\n".encode(),
    ]
    result = extract(parser)
    assert result.text == "Café" and result.page_count == 1


@pytest.mark.parametrize(
    "info, text, code",
    [
        (b"Pages: 101\nEncrypted: no\n", b"text", "PDF_PAGE_LIMIT"),
        (b"Pages: 1\nEncrypted: yes\n", b"text", "PDF_ENCRYPTED"),
        (b"Pages: 0\n", b"text", "PDF_INVALID"),
        (b"no page count", b"text", "PDF_INVALID"),
        (b"Pages: 1\n", b" \n\t", "PDF_NO_TEXT"),
        (b"Pages: 1\n", b"\xff", "PDF_INVALID"),
        (b"Pages: 1\n", b"x" * 1_000_001, "PDF_TEXT_LIMIT"),
    ],
    ids=[
        "too-many-pages",
        "encrypted-pdf",
        "zero-pages",
        "missing-page-count",
        "no-text",
        "invalid-utf8",
        "oversized-text",
    ],
)
def test_parser_failures_have_safe_codes(
    parser, info: bytes, text: bytes, code: str
) -> None:
    parser._run.side_effect = [info, text]
    with pytest.raises(ExtractionFailure) as error:
        extract(parser)
    assert error.value.code == code


def test_changed_source_is_rejected_before_subprocess(parser) -> None:
    with tempfile.TemporaryFile() as handle:
        handle.write(b"changed")
        with pytest.raises(ExtractionFailure, match="PDF_INTEGRITY_MISMATCH"):
            asyncio.run(
                parser.extract(
                    handle, expected_sha256=hashlib.sha256(b"original").hexdigest()
                )
            )
    parser._run.assert_not_awaited()


def test_timeout_is_reported_without_parser_details(parser) -> None:
    async def blocked(*_, **__):
        await asyncio.Event().wait()

    parser._settings = parser._settings.model_copy(
        update={"extraction_timeout_seconds": 0.01}
    )
    parser._run.side_effect = blocked
    with pytest.raises(ExtractionFailure, match="PDF_TIMEOUT"):
        extract(parser)


def test_subprocess_never_receives_application_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = PdfExtractor(Settings(_env_file=None))
    process = SimpleNamespace(
        stdout=SimpleNamespace(read=AsyncMock(side_effect=[b"safe", b""])),
        wait=AsyncMock(return_value=0),
    )
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(extractor, "_terminate", AsyncMock())
    monkeypatch.setenv("AGENTHIRE_POSTGRES_PASSWORD", "synthetic-private-password")
    with tempfile.TemporaryFile() as handle:
        assert (
            asyncio.run(extractor._run("pdfinfo", handle, ["-"], limit=1024)) == b"safe"
        )
    args, kwargs = spawn.await_args
    assert args[0] == TOOLS["prlimit"]
    assert "--as=268435456" in args and "--cpu=20" in args
    assert kwargs["stderr"] == asyncio.subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert set(kwargs["env"]) == {"PATH", "LANG", "LC_ALL"}


def tools_available() -> bool:
    return os.name == "posix" and all(Path(path).is_file() for path in TOOLS.values())


@pytest.mark.skipif(
    not tools_available(), reason="Real PDF tools run in the Docker/Linux worker."
)
def test_real_poppler_extracts_a_valid_pdf() -> None:
    result = extract(PdfExtractor(Settings(_env_file=None)), sample_pdf())
    assert result.text == "Candidate document smoke" and result.page_count == 1


@pytest.mark.skipif(
    not tools_available(), reason="Real PDF tools run in the Docker/Linux worker."
)
@pytest.mark.parametrize("blank", [True, False])
def test_real_poppler_rejects_empty_or_malformed_pdf(blank: bool) -> None:
    data = (
        sample_pdf().replace(b"Candidate document smoke", b" " * 24)
        if blank
        else b"%PDF-1.7\ninvalid\n%%EOF"
    )
    with pytest.raises(ExtractionFailure) as error:
        extract(PdfExtractor(Settings(_env_file=None)), data)
    assert error.value.code == ("PDF_NO_TEXT" if blank else "PDF_INVALID")


@pytest.mark.skipif(not tools_available(), reason="Real process limits run in Linux.")
def test_oversized_subprocess_output_is_killed_and_reaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = PdfExtractor(Settings(_env_file=None))
    monkeypatch.setitem(TOOLS, "writer", sys.executable)
    captured = []
    original = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        captured.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with (
        tempfile.TemporaryFile() as handle,
        pytest.raises(ExtractionFailure, match="PDF_TEXT_LIMIT"),
    ):
        asyncio.run(
            asyncio.wait_for(
                extractor._run(
                    "writer",
                    handle,
                    [
                        "-c",
                        "import sys,time;sys.stdout.write('x'*2000000);sys.stdout.flush();time.sleep(30)",
                    ],
                    limit=1024,
                ),
                timeout=3,
            )
        )
    assert captured[0].returncode is not None


@pytest.mark.parametrize(
    "field, value",
    [
        ("extraction_max_pages", 0),
        ("extraction_max_pages", 501),
        ("extraction_max_text_bytes", 1023),
        ("extraction_timeout_seconds", 0),
        ("extraction_process_memory_mb", 63),
        ("extraction_max_attempts", 0),
        ("extraction_poll_seconds", 0),
        ("extraction_lease_seconds", 29),
    ],
)
def test_extraction_configuration_is_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
