import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.base import Base


def migration():
    path = (
        Path(__file__).parents[1]
        / "migrations/versions/0013_create_job_search_profiles.py"
    )
    spec = importlib.util.spec_from_file_location("job_retrieval_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render(action):
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={
            "as_sql": True,
            "output_buffer": output,
            "target_metadata": Base.metadata,
        },
    )
    with Operations.context(context):
        getattr(migration(), action)()
    return output.getvalue()


def test_upgrade_has_unique_job_owner_revision_actor_and_cascade():
    sql = render("upgrade")
    assert "CREATE TABLE job_search_profiles" in sql
    assert (
        "PRIMARY KEY (job_id)" in sql
        and "REFERENCES jobs (id) ON DELETE CASCADE" in sql
    )
    assert "revision INTEGER DEFAULT '1' NOT NULL" in sql
    assert "REFERENCES users (id)" in sql
    assert "ck_job_search_profiles_query_text CHECK" in sql
    assert "ck_job_search_profiles_ck_" not in sql


def test_chain_and_downgrade_leave_existing_ingestion_search_and_jobs_intact():
    assert migration().down_revision == "0012_add_document_search"
    sql = render("downgrade")
    assert "DROP TABLE job_search_profiles" in sql
    assert "DROP TABLE jobs" not in sql and "DROP FUNCTION" not in sql
