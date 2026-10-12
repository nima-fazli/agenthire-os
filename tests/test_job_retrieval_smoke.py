import asyncio
import hashlib
from pathlib import Path

from app.core.document_storage import LocalDocumentStorage
from scripts.document_chunk_smoke import long_pdf
from scripts.job_retrieval_smoke import equivalent_resume_pdf


def test_equivalent_resume_fixture_passes_real_upload_validation(
    tmp_path: Path,
) -> None:
    original, duplicate = long_pdf(), equivalent_resume_pdf()
    assert original != duplicate
    assert original.rstrip() == duplicate.rstrip()
    storage = LocalDocumentStorage(tmp_path / "private")

    async def chunks(data: bytes):
        for offset in range(0, len(data), 4096):
            yield data[offset : offset + 4096]

    async def verify():
        stored = []
        for data in (original, duplicate):
            document = await storage.save_pdf(chunks(data), max_bytes=len(data))
            stored.append(document)
            assert document.sha256 == hashlib.sha256(data).hexdigest()
            assert document.size_bytes == len(data)
            handle = await storage.open(document.storage_key, expected_size=len(data))
            with handle:
                assert handle.read() == data
        assert stored[0].sha256 != stored[1].sha256
        for document in stored:
            await storage.delete(document.storage_key)
        assert list(storage.root.iterdir()) == []

    asyncio.run(verify())
