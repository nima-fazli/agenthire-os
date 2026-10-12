"""Create versioned document chunk sets with source offsets."""

import sqlalchemy as sa
from alembic import op

revision = "0011_create_document_chunks"
down_revision = "0010_create_document_extractions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_chunk_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_sha256", sa.String(64), nullable=False),
        sa.Column("source_text_sha256", sa.String(64), nullable=False),
        sa.Column("source_char_count", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("chunker_version", sa.String(32), nullable=False),
        sa.Column("chunk_max_chars", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap_chars", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunk_sets"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document_extractions.document_id"],
            name="fk_document_chunk_sets_document_id_document_extractions",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id",
            "source_text_sha256",
            "chunker_version",
            "chunk_max_chars",
            "chunk_overlap_chars",
            name="uq_document_chunk_sets_source_policy",
        ),
        sa.CheckConstraint(
            "source_char_count > 0",
            name=op.f("ck_document_chunk_sets_source_char_count"),
        ),
        sa.CheckConstraint(
            "page_count > 0", name=op.f("ck_document_chunk_sets_page_count")
        ),
        sa.CheckConstraint(
            "chunk_count > 0", name=op.f("ck_document_chunk_sets_chunk_count")
        ),
        sa.CheckConstraint(
            "chunk_max_chars > 0", name=op.f("ck_document_chunk_sets_chunk_max_chars")
        ),
        sa.CheckConstraint(
            "chunk_overlap_chars >= 0 AND chunk_overlap_chars < chunk_max_chars",
            name=op.f("ck_document_chunk_sets_chunk_overlap_chars"),
        ),
        sa.CheckConstraint(
            "length(source_text_sha256) = 64",
            name=op.f("ck_document_chunk_sets_text_digest"),
        ),
        sa.CheckConstraint(
            "length(source_document_sha256) = 64",
            name=op.f("ck_document_chunk_sets_document_digest"),
        ),
    )
    op.create_table(
        "document_chunks",
        sa.Column("chunk_set_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("chunk_set_id", "position", name="pk_document_chunks"),
        sa.ForeignKeyConstraint(
            ["chunk_set_id"],
            ["document_chunk_sets.id"],
            name="fk_document_chunks_chunk_set_id_document_chunk_sets",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "chunk_set_id", "start_offset", name="uq_document_chunks_start"
        ),
        sa.CheckConstraint("position >= 0", name=op.f("ck_document_chunks_position")),
        sa.CheckConstraint(
            "start_offset >= 0", name=op.f("ck_document_chunks_start_offset")
        ),
        sa.CheckConstraint(
            "end_offset > start_offset", name=op.f("ck_document_chunks_end_offset")
        ),
        sa.CheckConstraint(
            "length(text) = end_offset - start_offset",
            name=op.f("ck_document_chunks_text_length"),
        ),
        sa.CheckConstraint(
            "length(sha256) = 64", name=op.f("ck_document_chunks_digest")
        ),
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("document_chunk_sets")
