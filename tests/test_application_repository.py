import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.repositories.application import ApplicationRepository


def test_create_application_flushes_and_refreshes_without_commit() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()

    organization_id = uuid4()
    job_id = uuid4()
    candidate_id = uuid4()

    repository = ApplicationRepository(session)

    application = asyncio.run(
        repository.create(organization_id=organization_id, job_id=job_id, candidate_id=candidate_id)
    )

    assert application.organization_id == organization_id
    assert application.job_id == job_id
    assert application.candidate_id == candidate_id

    session.add.assert_called_once_with(application)
    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(application)
    session.commit.assert_not_awaited()


def test_get_by_job_and_candidate_is_tenant_scoped() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()

    organization_id = uuid4()
    job_id = uuid4()
    candidate_id = uuid4()

    application = Application(
        id=uuid4(), organization_id=organization_id, job_id=job_id, candidate_id=candidate_id
    )

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = application
    session.execute.return_value = query_result

    repository = ApplicationRepository(session)

    result = asyncio.run(
        repository.get_by_job_and_candidate(
            organization_id=organization_id, job_id=job_id, candidate_id=candidate_id
        )
    )

    assert result is application

    statement = session.execute.await_args.args[0]
    statement_text = str(statement)

    assert "applications.organization_id" in statement_text
    assert "applications.job_id" in statement_text
    assert "applications.candidate_id" in statement_text

    params = set(statement.compile().params.values())

    assert organization_id in params
    assert job_id in params
    assert candidate_id in params


def test_list_applications_is_scoped_to_organization() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()

    organization_id = uuid4()

    applications = [
        Application(
            id=uuid4(), organization_id=organization_id, job_id=uuid4(), candidate_id=uuid4()
        ),
        Application(
            id=uuid4(), organization_id=organization_id, job_id=uuid4(), candidate_id=uuid4()
        ),
    ]

    scalar_result = MagicMock()
    scalar_result.all.return_value = applications

    query_result = MagicMock()
    query_result.scalars.return_value = scalar_result
    session.execute.return_value = query_result

    repository = ApplicationRepository(session)

    result = asyncio.run(repository.list_for_organization(organization_id))

    assert result == applications

    statement = session.execute.await_args.args[0]

    assert "applications.organization_id" in str(statement)
    assert organization_id in set(statement.compile().params.values())


def test_get_application_is_scoped_to_organization() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()

    organization_id = uuid4()
    application_id = uuid4()

    application = Application(
        id=application_id, organization_id=organization_id, job_id=uuid4(), candidate_id=uuid4()
    )

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = application
    session.execute.return_value = query_result

    repository = ApplicationRepository(session)

    result = asyncio.run(
        repository.get_for_organization(
            application_id=application_id, organization_id=organization_id
        )
    )

    assert result is application

    statement = session.execute.await_args.args[0]
    statement_text = str(statement)

    assert "applications.id" in statement_text
    assert "applications.organization_id" in statement_text

    params = set(statement.compile().params.values())

    assert application_id in params
    assert organization_id in params
    assert "FOR UPDATE" not in statement_text
    assert "populate_existing" not in statement.get_execution_options()


def test_get_application_returns_none_when_not_found() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = None
    session.execute.return_value = query_result

    repository = ApplicationRepository(session)

    result = asyncio.run(
        repository.get_for_organization(application_id=uuid4(), organization_id=uuid4())
    )

    assert result is None


def test_get_application_for_update_locks_scoped_row_and_refreshes_identity() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    application_id = uuid4()
    organization_id = uuid4()

    application = Application(
        id=application_id,
        organization_id=organization_id,
        job_id=uuid4(),
        candidate_id=uuid4(),
        status="screening",
    )

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = application
    session.execute.return_value = query_result

    repository = ApplicationRepository(session)

    result = asyncio.run(
        repository.get_for_organization(
            application_id=application_id, organization_id=organization_id, for_update=True
        )
    )

    assert result is application

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "FOR UPDATE" in sql
    assert "applications.id =" in sql
    assert "applications.organization_id =" in sql
    assert set(compiled.params.values()) == {application_id, organization_id}
    assert statement.get_execution_options()["populate_existing"] is True
    session.commit.assert_not_awaited()


def test_update_application_status_flushes_and_refreshes_without_commit() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    application = Application(
        id=uuid4(), organization_id=uuid4(), job_id=uuid4(), candidate_id=uuid4(), status="applied"
    )

    repository = ApplicationRepository(session)

    result = asyncio.run(repository.update_status(application, status="screening"))

    assert result is application
    assert application.status == "screening"

    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(application)
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
