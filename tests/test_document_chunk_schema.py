from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.document_chunk import ChunkingRequest, ChunkSetRead, DocumentChunkRead


@pytest.mark.parametrize(
    "payload",
    [
        {"chunk_max_chars": 0},
        {"document_id": str(uuid4())},
        {"source_text_sha256": "a" * 64},
        {"text": "invented source"},
        {"force": True},
    ],
)
def test_clients_cannot_change_policy_provenance_or_source(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ChunkingRequest(**payload)


def test_request_accepts_only_the_empty_object() -> None:
    assert ChunkingRequest().model_dump() == {}


def test_set_metadata_does_not_include_source_text_or_storage_paths() -> None:
    value = ChunkSetRead(
        id=uuid4(),
        document_id=uuid4(),
        source_document_sha256="a" * 64,
        source_text_sha256="b" * 64,
        source_char_count=10,
        page_count=1,
        chunker_version="char-window-v1",
        chunk_max_chars=1200,
        chunk_overlap_chars=150,
        chunk_count=1,
        created_at=datetime.now(UTC),
    ).model_dump()
    assert "text" not in value and "storage_key" not in value
    assert value["source_document_sha256"] == "a" * 64


def test_chunk_offsets_and_checksum_survive_serialization() -> None:
    value = DocumentChunkRead(
        chunk_set_id=uuid4(),
        position=0,
        start_offset=2,
        end_offset=6,
        text="متن!",
        sha256="a" * 64,
    )
    assert DocumentChunkRead.model_validate_json(value.model_dump_json()) == value
