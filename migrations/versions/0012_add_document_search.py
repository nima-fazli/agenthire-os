"""Add immutable Unicode search normalization and document search indexes."""

import sqlalchemy as sa
from alembic import op

revision = "0012_add_document_search"
down_revision = "0011_create_document_chunks"
branch_labels = None
depends_on = None

NORMALIZER_SQL = r"""
CREATE FUNCTION public.agenthire_search_text_v1(value text)
RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
AS $function$
    SELECT btrim(regexp_replace(
        regexp_replace(
            translate(
                lower(normalize(value, NFKC) COLLATE pg_catalog.pg_unicode_fast),
                U&'\064A\0649\0643\200C\200D\0640',
                U&'\06CC\06CC\06A9  '
            ),
            U&'[\064B-\065F\0670\06D6-\06ED]', '', 'g'
        ),
        '[[:space:]]+', ' ', 'g'
    ));
$function$
"""


def upgrade() -> None:
    op.execute(NORMALIZER_SQL)
    op.create_index(
        "ix_document_chunks_search_v1",
        "document_chunks",
        [sa.text("to_tsvector('simple'::regconfig, agenthire_search_text_v1(text))")],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_document_chunk_sets_latest",
        "document_chunk_sets",
        ["document_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunk_sets_latest", table_name="document_chunk_sets")
    op.drop_index("ix_document_chunks_search_v1", table_name="document_chunks")
    op.execute("DROP FUNCTION public.agenthire_search_text_v1(text)")
