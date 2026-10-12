from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.text_search import LATEST_SET_INDEX, SEARCH_INDEX
from app.db.base import Base


class DocumentChunkSet(Base):
    __tablename__ = "document_chunk_sets"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "source_text_sha256",
            "chunker_version",
            "chunk_max_chars",
            "chunk_overlap_chars",
            name="uq_document_chunk_sets_source_policy",
        ),
        CheckConstraint("source_char_count > 0", name="source_char_count"),
        CheckConstraint("page_count > 0", name="page_count"),
        CheckConstraint("chunk_count > 0", name="chunk_count"),
        CheckConstraint("chunk_max_chars > 0", name="chunk_max_chars"),
        CheckConstraint(
            "chunk_overlap_chars >= 0 AND chunk_overlap_chars < chunk_max_chars",
            name="chunk_overlap_chars",
        ),
        CheckConstraint("length(source_text_sha256) = 64", name="text_digest"),
        CheckConstraint("length(source_document_sha256) = 64", name="document_digest"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("document_extractions.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_max_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_overlap_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index(
            SEARCH_INDEX,
            text("to_tsvector('simple'::regconfig, agenthire_search_text_v1(text))"),
            postgresql_using="gin",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint("start_offset >= 0", name="start_offset"),
        CheckConstraint("end_offset > start_offset", name="end_offset"),
        CheckConstraint("length(text) = end_offset - start_offset", name="text_length"),
        CheckConstraint("length(sha256) = 64", name="digest"),
        UniqueConstraint(
            "chunk_set_id", "start_offset", name="uq_document_chunks_start"
        ),
    )

    chunk_set_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("document_chunk_sets.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)


Index(
    LATEST_SET_INDEX,
    DocumentChunkSet.document_id,
    DocumentChunkSet.created_at.desc(),
    DocumentChunkSet.id.desc(),
)
