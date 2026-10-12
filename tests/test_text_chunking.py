import pytest

from app.core import text_chunking
from app.core.text_chunking import ChunkingFailure, chunk_text, text_digest


@pytest.mark.parametrize("length", [1, 4, 5, 7, 8, 9, 15, 32, 257, 1201])
@pytest.mark.parametrize("overlap", [0, 1, 3])
def test_windows_cover_source_exactly_without_gaps(length: int, overlap: int) -> None:
    source = ("Ada Python SQL\n" * 100)[:length]
    chunks = chunk_text(source, max_chars=4, overlap_chars=overlap, max_count=2000)
    reconstructed = chunks[0].text
    assert chunks[0].start_offset == 0
    for position, chunk in enumerate(chunks):
        assert chunk.position == position
        assert chunk.text == source[chunk.start_offset : chunk.end_offset]
        assert chunk.sha256 == text_digest(chunk.text)
        assert 0 < len(chunk.text) <= 4
        if position:
            previous = chunks[position - 1]
            assert chunk.start_offset == previous.end_offset - overlap
            reconstructed += chunk.text[overlap:]
    assert chunks[-1].end_offset == len(source)
    assert reconstructed == source
    assert chunks == chunk_text(
        source, max_chars=4, overlap_chars=overlap, max_count=2000
    )


def test_unicode_offsets_use_characters_and_keep_exact_source() -> None:
    source = "  مهندس 👩‍💻\ne\u0301 Python\t "
    chunks = chunk_text(source, max_chars=8, overlap_chars=2, max_count=20)
    assert chunks[0].text.startswith("  ")
    assert chunks[-1].text.endswith("\t ")
    for chunk in chunks:
        assert chunk.text.encode("utf-8").decode("utf-8") == chunk.text
        assert source[chunk.start_offset : chunk.end_offset] == chunk.text
    assert len(source.encode("utf-8")) > len(source)


@pytest.mark.parametrize(
    "source", ["", " ", "\n\t"], ids=["empty", "space", "whitespace"]
)
def test_empty_source_has_a_safe_failure(source: str) -> None:
    with pytest.raises(ChunkingFailure, match="CHUNK_SOURCE_EMPTY"):
        chunk_text(source, max_chars=8, overlap_chars=2, max_count=20)


@pytest.mark.parametrize(
    "size, overlap, count", [(0, 0, 1), (8, -1, 1), (8, 8, 1), (8, 9, 1), (8, 0, 0)]
)
def test_policy_must_make_progress(size: int, overlap: int, count: int) -> None:
    with pytest.raises(ValueError, match="Invalid chunking policy"):
        chunk_text("source", max_chars=size, overlap_chars=overlap, max_count=count)


def test_count_limit_is_checked_before_allocating_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(_):
        raise AssertionError("Chunk allocation started before the limit check")

    monkeypatch.setattr(text_chunking, "text_digest", forbidden)
    with pytest.raises(ChunkingFailure, match="CHUNK_LIMIT_EXCEEDED"):
        chunk_text("x" * 19, max_chars=8, overlap_chars=3, max_count=3)


def test_exact_count_boundary_is_accepted() -> None:
    chunks = chunk_text("x" * 18, max_chars=8, overlap_chars=3, max_count=3)
    assert len(chunks) == 3 and chunks[-1].end_offset == 18
