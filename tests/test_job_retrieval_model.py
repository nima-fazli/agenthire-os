import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import Job, JobSearchProfile, Organization, OrganizationMembership, User
from app.repositories.job_retrieval import JobRetrievalRepository


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
            JobSearchProfile.__table__,
        ],
    )
    user, org, job = uuid4(), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(User),
            {"id": user, "email": "profile@example.com", "password_hash": "hash"},
        )
        connection.execute(
            insert(Organization), {"id": org, "name": "Profiles", "slug": "profiles"}
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
    yield (
        engine,
        {"job_id": job, "query_text": "Python SQL", "updated_by_user_id": user},
        org,
    )
    engine.dispose()


@pytest.mark.parametrize(
    "bad",
    [
        {"job_id": uuid4()},
        {"updated_by_user_id": uuid4()},
        {"query_text": ""},
        {"query_text": " "},
        {"query_text": "x" * 257},
        {"revision": 0},
        {"revision": -1},
    ],
    ids=["job", "user", "empty", "blank", "long", "zero", "negative"],
)
def test_database_rejects_invalid_profile(database, bad):
    engine, values, _ = database
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert(JobSearchProfile), values | bad)


def test_one_profile_per_job_and_job_deletion_cascades(database):
    engine, values, _ = database
    with engine.begin() as connection:
        connection.execute(insert(JobSearchProfile), values)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert(JobSearchProfile), values | {"query_text": "PostgreSQL"}
        )
    with engine.begin() as connection:
        connection.execute(delete(Job).where(Job.id == values["job_id"]))
        assert connection.execute(select(JobSearchProfile)).all() == []


def test_repository_persists_revisions_idempotency_and_scoped_reads(database):
    engine, values, org = database

    class Adapter:
        def __init__(self, session):
            self.session = session

        def add(self, value):
            self.session.add(value)

        async def flush(self):
            self.session.flush()

        async def refresh(self, value):
            self.session.refresh(value)

        async def execute(self, statement):
            return self.session.execute(statement)

    async def verify():
        with Session(engine, expire_on_commit=False) as session:
            repository = JobRetrievalRepository(Adapter(session))
            scope = {
                "job_id": values["job_id"],
                "user_id": values["updated_by_user_id"],
                "organization_id": org,
            }
            assert await repository.lock_job(**scope) == values["job_id"]
            assert await repository.get_profile(**scope) is None
            profile = await repository.save_profile(
                None, job_id=scope["job_id"], user_id=scope["user_id"], q="Python SQL"
            )
            session.commit()
            assert profile.revision == 1
            assert await repository.get_profile(**scope) is profile
            before = profile.updated_at
            assert (
                await repository.save_profile(
                    profile, job_id=scope["job_id"], user_id=uuid4(), q="Python SQL"
                )
                is profile
            )
            assert profile.revision == 1 and profile.updated_at == before
            assert profile.updated_by_user_id == scope["user_id"]
            await repository.save_profile(
                profile,
                job_id=scope["job_id"],
                user_id=scope["user_id"],
                q="PostgreSQL",
            )
            session.commit()
            assert profile.revision == 2 and profile.query_text == "PostgreSQL"
            for bad in (
                {"user_id": uuid4()},
                {"organization_id": uuid4()},
                {"job_id": uuid4()},
            ):
                assert await repository.get_profile(**(scope | bad)) is None
                assert await repository.lock_job(**(scope | bad)) is None

    asyncio.run(verify())
