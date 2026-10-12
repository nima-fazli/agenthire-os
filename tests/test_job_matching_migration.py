import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.base import Base


def migration():
    path = (
        Path(__file__).parents[1]
        / "migrations/versions/0014_create_job_match_profiles.py"
    )
    spec = importlib.util.spec_from_file_location("job_matching_migration", path)
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


def test_upgrade_creates_parent_before_bounded_unique_criteria():
    sql = render("upgrade")
    assert sql.index("CREATE TABLE job_match_profiles") < sql.index(
        "CREATE TABLE job_match_criteria"
    )
    assert "PRIMARY KEY (job_id, position)" in sql and "UNIQUE (job_id, key)" in sql
    assert (
        "position BETWEEN 0 AND 9" in sql
        and "importance IN ('required', 'preferred')" in sql
    )
    assert "REFERENCES job_match_profiles (job_id) ON DELETE CASCADE" in sql
    assert "ck_job_match_criteria_ck_" not in sql


def test_downgrade_removes_only_new_tables_in_dependency_order():
    sql = render("downgrade")
    assert sql.index("DROP TABLE job_match_criteria") < sql.index(
        "DROP TABLE job_match_profiles"
    )
    assert "DROP TABLE jobs" not in sql and "DROP TABLE job_search_profiles" not in sql
    assert migration().down_revision == "0013_create_job_search_profiles"
