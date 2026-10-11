import asyncio
import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.document_storage import DocumentStorageError, LocalDocumentStorage
from app.core.errors import AppError

PDF = b"%PDF-1.7\nprivate resume\n%%EOF\n"


async def chunks(data: bytes):
    for offset in range(0, len(data), 3):
        yield data[offset : offset + 3]


def test_pdf_round_trip_and_repeatable_delete(tmp_path: Path) -> None:
    storage = LocalDocumentStorage(tmp_path / "private")
    stored = asyncio.run(storage.save_pdf(chunks(PDF), max_bytes=len(PDF)))
    assert stored.size_bytes == len(PDF)
    assert stored.sha256 == hashlib.sha256(PDF).hexdigest()
    handle = asyncio.run(storage.open(stored.storage_key, expected_size=len(PDF)))
    with handle:
        assert handle.read() == PDF
    asyncio.run(storage.delete(stored.storage_key))
    asyncio.run(storage.delete(stored.storage_key))
    assert list(storage.root.iterdir()) == []


@pytest.mark.parametrize(
    "data", [b"", b"<html>resume</html>", b"%PDF-1.7\ntruncated", b"%PDF-9.0\n%%EOF"]
)
def test_invalid_pdf_removes_temporary_file(tmp_path: Path, data: bytes) -> None:
    storage = LocalDocumentStorage(tmp_path)
    with pytest.raises(AppError) as error:
        asyncio.run(storage.save_pdf(chunks(data), max_bytes=1024))
    assert error.value.code == "INVALID_PDF"
    assert list(tmp_path.iterdir()) == []


def test_actual_stream_size_is_enforced(tmp_path: Path) -> None:
    with pytest.raises(AppError) as error:
        asyncio.run(
            LocalDocumentStorage(tmp_path).save_pdf(chunks(PDF), max_bytes=len(PDF) - 1)
        )
    assert error.value.status_code == 413
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("exception", [RuntimeError, asyncio.CancelledError])
def test_interrupted_stream_is_cleaned(
    tmp_path: Path, exception: type[BaseException]
) -> None:
    async def interrupted():
        yield b"%PDF-1.7"
        raise exception()

    with pytest.raises(exception):
        asyncio.run(
            LocalDocumentStorage(tmp_path).save_pdf(interrupted(), max_bytes=1024)
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "key", ["../secret.pdf", "/etc/passwd", "a.pdf", "a" * 32 + ".txt"]
)
def test_untrusted_storage_keys_are_rejected(tmp_path: Path, key: str) -> None:
    with pytest.raises(DocumentStorageError):
        asyncio.run(LocalDocumentStorage(tmp_path).delete(key))


def test_missing_or_corrupt_object_is_unavailable(tmp_path: Path) -> None:
    storage = LocalDocumentStorage(tmp_path)
    stored = asyncio.run(storage.save_pdf(chunks(PDF), max_bytes=1024))
    with pytest.raises(DocumentStorageError):
        asyncio.run(storage.open(stored.storage_key, expected_size=len(PDF) + 1))
    asyncio.run(storage.delete(stored.storage_key))
    with pytest.raises(DocumentStorageError):
        asyncio.run(storage.open(stored.storage_key, expected_size=len(PDF)))


def test_symlink_cannot_expose_an_external_file(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir()
    secret = tmp_path / "outside.pdf"
    secret.write_bytes(PDF)
    key = "a" * 32 + ".pdf"
    try:
        (root / key).symlink_to(secret)
    except OSError:
        pytest.skip("Creating symlinks requires platform privileges.")
    with pytest.raises(DocumentStorageError):
        asyncio.run(LocalDocumentStorage(root).open(key, expected_size=len(PDF)))
    assert secret.read_bytes() == PDF


def test_storage_settings_read_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENTHIRE_DOCUMENT_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("AGENTHIRE_DOCUMENT_MAX_BYTES", "2048")
    settings = Settings(_env_file=None)
    assert settings.document_storage_path == tmp_path
    assert settings.document_max_bytes == 2048


@pytest.mark.parametrize("size", [0, -1, 1023, 50 * 1024 * 1024 + 1])
def test_unsafe_storage_limit_is_rejected(size: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, document_max_bytes=size)


@pytest.mark.parametrize("value", ["", " ", ".", "..", "/"])
def test_storage_requires_a_dedicated_directory(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, document_storage_path=value)


@pytest.mark.parametrize("seconds", [0, 301])
def test_upload_timeout_must_be_bounded(seconds: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, document_upload_timeout_seconds=seconds)
