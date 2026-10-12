from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChunkingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChunkSetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    source_document_sha256: str
    source_text_sha256: str
    source_char_count: int
    page_count: int
    chunker_version: str
    chunk_max_chars: int
    chunk_overlap_chars: int
    chunk_count: int
    created_at: datetime


class DocumentChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    chunk_set_id: UUID
    position: int
    start_offset: int
    end_offset: int
    text: str
    sha256: str


class ChunkSetPage(BaseModel):
    items: list[ChunkSetRead]
    total: int
    limit: int
    offset: int


class DocumentChunkPage(BaseModel):
    chunk_set: ChunkSetRead
    items: list[DocumentChunkRead]
    total: int
    limit: int
    offset: int
