import asyncio
import hashlib

import pytest

from app.core.document_storage import LocalDocumentStorage
from app.services.retrieval_evaluation import suite_digest
from scripts import evaluation_cases
from scripts.evaluation_cases import (
    ITEM_KEYS,
    RESUME_TEXT,
    ascii_resume_pdf,
    load_example,
    load_suite,
)


def test_reference_labels_and_example_origin_preserve_the_known_split_term_limit():
    suite, example = load_suite(), load_example()
    assert (
        example.suite_sha256 == suite_digest(suite) and example.source_kind == "example"
    )
    assert suite.label_kind == "synthetic_reference"
    assert (
        len(suite.ranking) == 5
        and len(suite.evidence) == 7
        and len(suite.criteria) == 5
    )
    combined = next(case for case in suite.ranking if case.key == "rank-combined")
    observed = next(case for case in example.ranking if case.key == "rank-combined")
    assert combined.judgments["bruno"] == 1 and "bruno" not in observed.ranked_ids
    bruno = next(case for case in suite.evidence if case.item_id == "bruno")
    assert (
        bruno.expected["python"]
        and bruno.expected["sql"]
        and not bruno.expected["together"]
    )


def test_reference_covers_all_candidate_keys_and_forbids_the_other_tenant():
    for case in load_suite().ranking:
        assert set(case.judgments) == set(ITEM_KEYS)
        assert (
            case.forbidden == ["other-tenant"] and case.judgments["other-tenant"] == 0
        )


def test_changing_corpus_bytes_requires_updated_reference_fingerprint(monkeypatch):
    monkeypatch.setitem(evaluation_cases.RESUME_TEXT, "ada", "Changed reference PDF")
    with pytest.raises(ValueError, match="fingerprint"):
        load_suite()


@pytest.mark.parametrize("text", ["", " ", "line\nline", "پایتون", "x" * 121])
def test_pdf_factory_rejects_unsupported_fixture_text(text):
    with pytest.raises(ValueError):
        ascii_resume_pdf(text)


def test_pdf_literal_escapes_parentheses_and_backslashes():
    data = ascii_resume_pdf(r"Python (SQL) C:\code")
    assert b"Python \\(SQL\\) C:\\\\code" in data


def test_fixture_pdfs_have_valid_xrefs_and_pass_real_streamed_upload_validation(
    tmp_path,
):
    values = [ascii_resume_pdf(text) for text in RESUME_TEXT.values()]
    original = ascii_resume_pdf(RESUME_TEXT["ada"])
    values += [original + b"\n", original + b"\n\n"]
    for data in values:
        xref = int(data.rsplit(b"startxref\n", 1)[1].splitlines()[0])
        lines = data[xref:].splitlines()
        assert lines[0] == b"xref"
        for number, line in enumerate(lines[3:8], 1):
            assert data[int(line.split()[0]) :].startswith(f"{number} 0 obj\n".encode())
    assert (
        len(
            {
                hashlib.sha256(data).hexdigest()
                for data in (original, original + b"\n", original + b"\n\n")
            }
        )
        == 3
    )
    storage = LocalDocumentStorage(tmp_path / "private")

    async def stream(data):
        for start in range(0, len(data), 37):
            yield data[start : start + 37]

    async def verify():
        for data in values:
            stored = await storage.save_pdf(stream(data), max_bytes=len(data))
            assert stored.sha256 == hashlib.sha256(data).hexdigest()
            await storage.delete(stored.storage_key)
        assert list(storage.root.iterdir()) == []

    asyncio.run(verify())
