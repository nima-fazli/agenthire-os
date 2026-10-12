import asyncio
from pathlib import Path

from app.core.document_storage import LocalDocumentStorage
from scripts.job_matching_smoke import split_skills_pdf


def test_split_skill_pdf_and_duplicate_pass_real_upload_validation(tmp_path: Path):
    original, duplicate = split_skills_pdf(), split_skills_pdf(duplicate=True)
    assert original != duplicate and original.rstrip() == duplicate.rstrip()
    xref = int(original.rsplit(b"startxref\n", 1)[1].splitlines()[0])
    assert original[xref:].startswith(b"xref\n")
    lines = original[xref:].splitlines()
    count = int(lines[1].split()[1])
    for number, line in enumerate(lines[3 : 3 + count - 1], 1):
        offset = int(line.split()[0])
        assert original[offset:].startswith(f"{number} 0 obj\n".encode())
    storage = LocalDocumentStorage(tmp_path / "private")

    async def stream(data):
        for offset in range(0, len(data), 4096):
            yield data[offset : offset + 4096]

    async def verify():
        values = [
            await storage.save_pdf(stream(data), max_bytes=len(data))
            for data in (original, duplicate)
        ]
        assert values[0].sha256 != values[1].sha256
        for value in values:
            await storage.delete(value.storage_key)
        assert list(storage.root.iterdir()) == []

    asyncio.run(verify())
