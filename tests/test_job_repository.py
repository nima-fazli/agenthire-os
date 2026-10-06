import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.repositories.job import JobRepository


def test_create_job_flushes_and_refreshes_without_commit() -> None:
    session = MagicMock(
        spec=AsyncSession
    )

    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()

    organization_id = uuid4()

    repository = JobRepository(
        session
    )

    job = asyncio.run(
        repository.create(
            organization_id=organization_id,
            title="Backend Engineer",
            description="Build backend systems.",
            status="draft",
        )
    )

    assert job.organization_id == organization_id
    assert job.title == "Backend Engineer"
    assert job.status == "draft"

    session.add.assert_called_once_with(
        job
    )

    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(
        job
    )

    session.commit.assert_not_awaited()


def test_list_jobs_is_scoped_to_organization() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.execute = AsyncMock()

    organization_id = uuid4()

    jobs = [
        Job(
            id=uuid4(),
            organization_id=organization_id,
            title="Backend Engineer",
            description="Backend work.",
            status="draft",
        ),
        Job(
            id=uuid4(),
            organization_id=organization_id,
            title="AI Engineer",
            description="AI work.",
            status="open",
        ),
    ]

    scalar_result = MagicMock()
    scalar_result.all.return_value = jobs

    query_result = MagicMock()
    query_result.scalars.return_value = scalar_result

    session.execute.return_value = query_result

    repository = JobRepository(
        session
    )

    result = asyncio.run(
        repository.list_for_organization(
            organization_id
        )
    )

    assert result == jobs

    statement = session.execute.await_args.args[
        0
    ]

    statement_text = str(
        statement
    )

    assert "jobs.organization_id" in statement_text

    assert organization_id in set(
        statement.compile().params.values()
    )


def test_get_job_is_scoped_to_organization() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.execute = AsyncMock()

    organization_id = uuid4()
    job_id = uuid4()

    job = Job(
        id=job_id,
        organization_id=organization_id,
        title="Backend Engineer",
        description="Backend work.",
        status="open",
    )

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = job

    session.execute.return_value = query_result

    repository = JobRepository(
        session
    )

    result = asyncio.run(
        repository.get_for_organization(
            job_id=job_id,
            organization_id=organization_id,
        )
    )

    assert result is job

    statement = session.execute.await_args.args[
        0
    ]

    statement_text = str(
        statement
    )

    assert "jobs.id" in statement_text
    assert "jobs.organization_id" in statement_text

    params = set(
        statement.compile().params.values()
    )

    assert job_id in params
    assert organization_id in params


def test_get_job_returns_none_when_not_found() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.execute = AsyncMock()

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = None

    session.execute.return_value = query_result

    repository = JobRepository(
        session
    )

    result = asyncio.run(
        repository.get_for_organization(
            job_id=uuid4(),
            organization_id=uuid4(),
        )
    )

    assert result is None
