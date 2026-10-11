import hashlib
import os
import re
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError


class DocumentStorageError(Exception):
    pass


@dataclass(frozen=True)
class StoredDocument:
    storage_key: str
    size_bytes: int
    sha256: str


class DocumentStorage(Protocol):
    async def save_pdf(
        self, chunks: AsyncIterator[bytes], *, max_bytes: int
    ) -> StoredDocument: ...
    async def open(self, storage_key: str, *, expected_size: int) -> BinaryIO: ...
    async def delete(self, storage_key: str) -> None: ...


def upload_error(code: str, message: str, status_code: int = 422) -> AppError:
    return AppError(code=code, message=message, status_code=status_code)


class LocalDocumentStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, storage_key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}\.pdf", storage_key):
            raise DocumentStorageError("Invalid storage key.")
        path = self.root / storage_key
        if path.is_symlink():
            raise DocumentStorageError("Symbolic links are not document objects.")
        return path

    def _temporary_file(self) -> tuple[Path, BinaryIO]:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".upload-", dir=self.root)
        return Path(name), os.fdopen(descriptor, "wb")

    @staticmethod
    def _publish(output: BinaryIO, temporary: Path, target: Path) -> None:
        output.flush()
        os.fsync(output.fileno())
        output.close()
        os.replace(temporary, target)

    async def save_pdf(
        self, chunks: AsyncIterator[bytes], *, max_bytes: int
    ) -> StoredDocument:
        temporary = None
        output = None
        size = 0
        digest = hashlib.sha256()
        header = b""
        tail = b""
        storage_key = f"{uuid4().hex}.pdf"
        try:
            temporary, output = await run_in_threadpool(self._temporary_file)
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise upload_error(
                        "DOCUMENT_TOO_LARGE", "Document exceeds the size limit.", 413
                    )
                header = (header + chunk)[:8]
                tail = (tail + chunk)[-1024:]
                digest.update(chunk)
                await run_in_threadpool(output.write, chunk)
            if not re.fullmatch(
                rb"%PDF-(?:1\.[0-7]|2\.0)", header
            ) or not tail.rstrip().endswith(b"%%EOF"):
                raise upload_error(
                    "INVALID_PDF", "Document must have a PDF header and end marker."
                )
            await run_in_threadpool(
                self._publish, output, temporary, self._path(storage_key)
            )
            return StoredDocument(storage_key, size, digest.hexdigest())
        except OSError as error:
            raise DocumentStorageError("Document storage is unavailable.") from error
        finally:
            if output is not None:
                await run_in_threadpool(output.close)
            if temporary is not None:
                await run_in_threadpool(temporary.unlink, missing_ok=True)

    def _open(self, storage_key: str, expected_size: int) -> BinaryIO:
        handle = self._path(storage_key).open("rb")
        try:
            if os.fstat(handle.fileno()).st_size != expected_size:
                raise DocumentStorageError(
                    "Stored document size does not match metadata."
                )
        except BaseException:
            handle.close()
            raise
        return handle

    async def open(self, storage_key: str, *, expected_size: int) -> BinaryIO:
        try:
            return await run_in_threadpool(self._open, storage_key, expected_size)
        except OSError as error:
            raise DocumentStorageError("Document storage is unavailable.") from error

    async def delete(self, storage_key: str) -> None:
        try:
            await run_in_threadpool(self._path(storage_key).unlink, missing_ok=True)
        except OSError as error:
            raise DocumentStorageError("Document storage is unavailable.") from error
