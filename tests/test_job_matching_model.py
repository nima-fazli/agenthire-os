import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import (
    Job,
    JobMatchCriterion,
    JobMatchProfile,
    Organization,
    OrganizationMembership,
    User,
)
from app.repositories.job_matching import JobMatchingRepository


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Organization.__table__,
            OrganizationMembership.__table__,
            Job.__table__,
            JobMatchProfile.__table__,
            JobMatchCriterion.__table__,
        ],
    )
    org, user, job = uuid4(), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(User),
            {"id": user, "email": "criteria@example.com", "password_hash": "hash"},
        )
        connection.execute(
            insert(Organization), {"id": org, "name": "Criteria", "slug": "criteria"}
        )
        connection.execute(
            insert(OrganizationMembership), {"organization_id": org, "user_id": user}
        )
        connection.execute(
            insert(Job),
            {
                "id": job,
                "organization_id": org,
                "title": "Engineer",
                "description": "Backend",
            },
        )
        connection.execute(
            insert(JobMatchProfile), {"job_id": job, "updated_by_user_id": user}
        )
    yield engine, {"organization_id": org, "user_id": user, "job_id": job}
    engine.dispose()


def criterion(parent_job_id, **overrides):
    return {
        "job_id": parent_job_id,
        "position": 0,
        "key": "python",
        "label": "Python",
        "query_text": "Python",
        "importance": "required",
    } | overrides


@pytest.mark.parametrize(
    "bad",
    [
        {"job_id": uuid4()},
        {"position": -1},
        {"position": 10},
        {"key": " "},
        {"label": " "},
        {"query_text": ""},
        {"query_text": "x" * 257},
        {"importance": "unknown"},
    ],
    ids=[
        "parent",
        "negative",
        "overflow",
        "key",
        "label",
        "empty-q",
        "long-q",
        "importance",
    ],
)
def test_database_enforces_criterion_ownership_bounds_and_vocabulary(database, bad):
    engine, scope = database
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert(JobMatchCriterion), criterion(scope["job_id"], **bad))


def test_duplicate_key_is_rejected_and_job_deletion_cascades(database):
    engine, scope = database
    with engine.begin() as connection:
        connection.execute(insert(JobMatchCriterion), criterion(scope["job_id"]))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert(JobMatchCriterion), criterion(scope["job_id"], position=1)
        )
    with engine.begin() as connection:
        connection.execute(delete(Job).where(Job.id == scope["job_id"]))
        assert connection.execute(select(JobMatchProfile)).all() == []
        assert connection.execute(select(JobMatchCriterion)).all() == []


@pytest.mark.parametrize(
    "bad",
    [{"revision": 0}, {"updated_by_user_id": uuid4()}, {"job_id": uuid4()}],
    ids=["revision", "writer", "job"],
)
def test_database_enforces_profile_revision_and_parent_references(database, bad):
    engine, scope = database
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            update(JobMatchProfile)
            .where(JobMatchProfile.job_id == scope["job_id"])
            .values(**bad)
        )


def test_repository_replaces_criteria_atomically_preserves_retries_and_scopes_reads(
    database,
):
    engine, scope = database

    class Adapter:
        def __init__(self, session):
            self.session = session

        def add(self, value):
            self.session.add(value)

        async def flush(self):
            self.session.flush()

        async def execute(self, *args):
            return self.session.execute(*args)

    async def verify():
        with Session(engine, expire_on_commit=False) as session:
            session.execute(
                delete(JobMatchProfile).where(JobMatchProfile.job_id == scope["job_id"])
            )
            session.commit()
            repo = JobMatchingRepository(Adapter(session))
            data = [
                {
                    "key": "python",
                    "label": "Python",
                    "q": "Python",
                    "importance": "required",
                },
                {"key": "sql", "label": "SQL", "q": "SQL", "importance": "preferred"},
            ]
            assert await repo.lock_job(**scope) == scope["job_id"]
            first = await repo.save_profile(None, **scope, criteria=data)
            session.commit()
            assert first["revision"] == 1 and [
                row["position"] for row in first["criteria"]
            ] == [0, 1]
            retry = await repo.save_profile(first, **scope, criteria=data)
            assert retry == first
            changed = await repo.save_profile(first, **scope, criteria=[data[1]])
            session.commit()
            assert changed["revision"] == 2 and changed["criteria"][0]["key"] == "sql"
            with pytest.raises(IntegrityError):
                await repo.save_profile(changed, **scope, criteria=[data[0], data[0]])
            session.rollback()
            assert await repo.get_profile(**scope) == changed
            for override in (
                {"user_id": uuid4()},
                {"organization_id": uuid4()},
                {"job_id": uuid4()},
            ):
                assert await repo.get_profile(**(scope | override)) is None

    asyncio.run(verify())
