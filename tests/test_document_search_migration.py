import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations


def migration():
    path = Path(__file__).parents[1] / "migrations/versions/0012_add_document_search.py"
    spec = importlib.util.spec_from_file_location("document_search_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render(action: str) -> str:
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        getattr(migration(), action)()
    return output.getvalue()


def test_upgrade_creates_frozen_normalizer_before_both_indexes() -> None:
    sql = render("upgrade")
    assert "IMMUTABLE STRICT PARALLEL SAFE" in sql
    assert "normalize(value, NFKC) COLLATE pg_catalog.pg_unicode_fast" in sql
    assert "CREATE OR REPLACE" not in sql
    assert sql.index("CREATE FUNCTION") < sql.index("USING gin")
    assert "agenthire_search_text_v1(text)" in sql
    assert "created_at DESC, id DESC" in sql


def test_downgrade_removes_dependent_indexes_before_function() -> None:
    sql = render("downgrade")
    assert sql.index("DROP INDEX ix_document_chunks_search_v1") < sql.index(
        "DROP FUNCTION"
    )
    assert "DROP TABLE" not in sql


def test_migration_keeps_normalization_self_contained() -> None:
    module = migration()
    assert module.down_revision == "0011_create_document_chunks"
    assert r"\064A\0649\0643\200C\200D\0640" in module.NORMALIZER_SQL
    assert r"\06CC\06CC\06A9" in module.NORMALIZER_SQL
