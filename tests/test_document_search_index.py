from alembic.migration import MigrationContext
from sqlalchemy import Index, create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.core.text_search import LATEST_SET_INDEX, SEARCH_INDEX
from app.db.base import Base
from app.models import (
    Candidate,
    CandidateDocument,
    DocumentChunk,
    DocumentChunkSet,
    DocumentExtraction,
    Organization,
    User,
)


def index(name: str, model):
    return next(item for item in model.__table__.indexes if item.name == name)


def test_postgres_search_index_uses_the_same_expression_as_queries() -> None:
    sql = str(
        CreateIndex(index(SEARCH_INDEX, DocumentChunk)).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "USING gin" in sql
    assert "to_tsvector('simple'::regconfig, agenthire_search_text_v1(text))" in sql


def test_latest_set_index_supports_document_and_stable_version_order() -> None:
    sql = str(
        CreateIndex(index(LATEST_SET_INDEX, DocumentChunkSet)).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "document_id, created_at DESC, id DESC" in sql


def test_expression_index_matches_postgres_reflection_for_alembic() -> None:
    metadata = index(SEARCH_INDEX, DocumentChunk)
    reflected = Index(
        SEARCH_INDEX,
        text("to_tsvector('simple'::regconfig, agenthire_search_text_v1(text))"),
        postgresql_using="gin",
    )
    context = MigrationContext.configure(dialect_name="postgresql")
    assert context.impl.compare_indexes(metadata, reflected).is_equal


def test_existing_sqlite_model_tests_do_not_require_postgres_functions() -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Organization.__table__,
                Candidate.__table__,
                CandidateDocument.__table__,
                DocumentExtraction.__table__,
                DocumentChunkSet.__table__,
                DocumentChunk.__table__,
            ],
        )
        assert SEARCH_INDEX not in {
            item["name"] for item in inspect(engine).get_indexes("document_chunks")
        }
        assert LATEST_SET_INDEX in {
            item["name"] for item in inspect(engine).get_indexes("document_chunk_sets")
        }
    finally:
        engine.dispose()
