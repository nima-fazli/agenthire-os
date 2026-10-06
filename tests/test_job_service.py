import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.job import Job
from app.models.organization_membership import (
    OrganizationMembership,
)
from app.repositories.job import JobRepository
from app.repositories.organization_membership import (
    OrganizationMembershipRepository,
)
from app.schemas.job import JobCreate
from app.services.job import JobService


def make_service() -> tuple[
    JobService,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    session = MagicMock(
        spec=AsyncSession
    )

    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    job_repository = MagicMock(
        spec=JobRepository
    )

    membership_repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    service = JobService(
        session
    )

    service._repository = job_repository
    service._membership_repository = (
        membership_repository
    )

    return (
        service,
        session,
        job_repository,
        membership_repository,
    )


def test_create_job_for_member_commits() -> None:
    (
        service,
        session,
        job_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = (
        OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    job = Job(
        id=uuid4(),
        organization_id=organization_id,
        title="Backend Engineer",
        description="Build backend systems.",
        status="draft",
    )

    job_repository.create.return_value = job

    data = JobCreate(
        title="Backend Engineer",
        description="Build backend systems.",
    )

    result = asyncio.run(
        service.create(
            data,
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    assert result is job

    membership_repository.get_by_user_and_organization.assert_awaited_once_with(
        user_id=user_id,
        organization_id=organization_id,
    )

    job_repository.create.assert_awaited_once_with(
        organization_id=organization_id,
        title="Backend Engineer",
        description="Build backend systems.",
        status="draft",
    )

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


def test_create_job_hides_organization_from_non_member() -> None:
    (
        service,
        session,
        job_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = None

    with pytest.raises(
        NotFoundError
    ) as error:
        asyncio.run(
            service.create(
                JobCreate(
                    title="Backend Engineer",
                    description="Backend work.",
                ),
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert error.value.status_code == 404
    assert (
        error.value.code
        == "ORGANIZATION_NOT_FOUND"
    )

    job_repository.create.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


def test_create_job_rolls_back_on_failure() -> None:
    (
        service,
        session,
        job_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = (
        OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    failure = RuntimeError(
        "database failure"
    )

    job_repository.create.side_effect = failure

    with pytest.raises(
        RuntimeError
    ) as error:
        asyncio.run(
            service.create(
                JobCreate(
                    title="Backend Engineer",
                    description="Backend work.",
                ),
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert error.value is failure

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_list_jobs_for_member() -> None:
    (
        service,
        _session,
        job_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = (
        OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    jobs = [
        Job(
            id=uuid4(),
            organization_id=organization_id,
            title="Backend Engineer",
            description="Backend work.",
            status="draft",
        )
    ]

    job_repository.list_for_organization.return_value = jobs

    result = asyncio.run(
        service.list_for_user(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    assert result == jobs

    job_repository.list_for_organization.assert_awaited_once_with(
        organization_id
    )


def test_list_jobs_hides_organization_from_non_member() -> None:
    (
        service,
        _session,
        job_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = None

    with pytest.raises(
        NotFoundError
    ) as error:
        asyncio.run(
            service.list_for_user(
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert (
        error.value.code
        == "ORGANIZATION_NOT_FOUND"
    )

    job_repository.list_for_organization.assert_not_awaited()


def test_get_job_for_member() -> None:
    (
        service,
        _session,
        job_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = (
        OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    job = Job(
        id=job_id,
        organization_id=organization_id,
        title="Backend Engineer",
        description="Backend work.",
        status="open",
    )

    job_repository.get_for_organization.return_value = job

    result = asyncio.run(
        service.get_for_user(
            job_id,
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    assert result is job

    job_repository.get_for_organization.assert_awaited_once_with(
        job_id=job_id,
        organization_id=organization_id,
    )


def test_get_job_returns_not_found_for_missing_job() -> None:
    (
        service,
        _session,
        job_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = (
        OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    job_repository.get_for_organization.return_value = None

    with pytest.raises(
        NotFoundError
    ) as error:
        asyncio.run(
            service.get_for_user(
                job_id,
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert error.value.status_code == 404
    assert error.value.code == "JOB_NOT_FOUND"
    assert error.value.details == {
        "organization_id": str(
            organization_id
        ),
        "job_id": str(
            job_id
        ),
    }


def test_get_job_hides_organization_from_non_member() -> None:
    (
        service,
        _session,
        job_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = None

    with pytest.raises(
        NotFoundError
    ) as error:
        asyncio.run(
            service.get_for_user(
                uuid4(),
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert (
        error.value.code
        == "ORGANIZATION_NOT_FOUND"
    )

    job_repository.get_for_organization.assert_not_awaited()
