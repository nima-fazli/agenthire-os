import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.organization_membership import (
    OrganizationMembership,
)
from app.repositories.application import ApplicationRepository
from app.repositories.candidate import CandidateRepository
from app.repositories.job import JobRepository
from app.repositories.organization_membership import (
    OrganizationMembershipRepository,
)
from app.schemas.application import ApplicationCreate
from app.services.application import ApplicationService


def make_service() -> tuple[
    ApplicationService,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    session = MagicMock(
        spec=AsyncSession
    )

    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    application_repository = MagicMock(
        spec=ApplicationRepository
    )
    job_repository = MagicMock(
        spec=JobRepository
    )
    candidate_repository = MagicMock(
        spec=CandidateRepository
    )
    membership_repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    service = ApplicationService(
        session
    )

    service._repository = (
        application_repository
    )
    service._job_repository = (
        job_repository
    )
    service._candidate_repository = (
        candidate_repository
    )
    service._membership_repository = (
        membership_repository
    )

    return (
        service,
        session,
        application_repository,
        job_repository,
        candidate_repository,
        membership_repository,
    )


def configure_valid_context(
    *,
    organization_id,
    user_id,
    job_id,
    candidate_id,
    job_repository,
    candidate_repository,
    membership_repository,
) -> None:
    membership_repository.get_by_user_and_organization.return_value = (
        OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    job_repository.get_for_organization.return_value = (
        Job(
            id=job_id,
            organization_id=organization_id,
            title="AI Engineer",
            description="Build AI systems.",
            status="open",
        )
    )

    candidate_repository.get_for_organization.return_value = (
        Candidate(
            id=candidate_id,
            organization_id=organization_id,
            full_name="Ada Lovelace",
        )
    )


def test_create_application_for_valid_tenant_commits() -> None:
    (
        service,
        session,
        application_repository,
        job_repository,
        candidate_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()
    candidate_id = uuid4()

    configure_valid_context(
        organization_id=organization_id,
        user_id=user_id,
        job_id=job_id,
        candidate_id=candidate_id,
        job_repository=job_repository,
        candidate_repository=candidate_repository,
        membership_repository=membership_repository,
    )

    application_repository.get_by_job_and_candidate.return_value = (
        None
    )

    application = Application(
        id=uuid4(),
        organization_id=organization_id,
        job_id=job_id,
        candidate_id=candidate_id,
    )

    application_repository.create.return_value = (
        application
    )

    result = asyncio.run(
        service.create(
            ApplicationCreate(
                job_id=job_id,
                candidate_id=candidate_id,
            ),
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    assert result is application

    application_repository.create.assert_awaited_once_with(
        organization_id=organization_id,
        job_id=job_id,
        candidate_id=candidate_id,
    )

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


def test_create_application_hides_organization_from_non_member() -> None:
    (
        service,
        session,
        application_repository,
        job_repository,
        candidate_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = (
        None
    )

    with pytest.raises(
        NotFoundError
    ) as error:
        asyncio.run(
            service.create(
                ApplicationCreate(
                    job_id=uuid4(),
                    candidate_id=uuid4(),
                ),
                organization_id=organization_id,
                user_id=uuid4(),
            )
        )

    assert (
        error.value.code
        == "ORGANIZATION_NOT_FOUND"
    )

    job_repository.get_for_organization.assert_not_awaited()
    candidate_repository.get_for_organization.assert_not_awaited()
    application_repository.create.assert_not_awaited()

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


def test_create_application_rejects_job_outside_tenant() -> None:
    (
        service,
        session,
        application_repository,
        job_repository,
        candidate_repository,
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

    job_repository.get_for_organization.return_value = (
        None
    )

    with pytest.raises(
        NotFoundError
    ) as error:
        asyncio.run(
            service.create(
                ApplicationCreate(
                    job_id=job_id,
                    candidate_id=uuid4(),
                ),
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert error.value.code == "JOB_NOT_FOUND"

    candidate_repository.get_for_organization.assert_not_awaited()
    application_repository.create.assert_not_awaited()

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


def test_create_application_rejects_candidate_outside_tenant() -> None:
    (
        service,
        session,
        application_repository,
        job_repository,
        candidate_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()
    candidate_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = (
        OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    job_repository.get_for_organization.return_value = (
        Job(
            id=job_id,
            organization_id=organization_id,
            title="AI Engineer",
            description="Build AI systems.",
            status="open",
        )
    )

    candidate_repository.get_for_organization.return_value = (
        None
    )

    with pytest.raises(
        NotFoundError
    ) as error:
        asyncio.run(
            service.create(
                ApplicationCreate(
                    job_id=job_id,
                    candidate_id=candidate_id,
                ),
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert (
        error.value.code
        == "CANDIDATE_NOT_FOUND"
    )

    application_repository.create.assert_not_awaited()

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


def test_create_application_rejects_existing_pair() -> None:
    (
        service,
        session,
        application_repository,
        job_repository,
        candidate_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()
    candidate_id = uuid4()

    configure_valid_context(
        organization_id=organization_id,
        user_id=user_id,
        job_id=job_id,
        candidate_id=candidate_id,
        job_repository=job_repository,
        candidate_repository=candidate_repository,
        membership_repository=membership_repository,
    )

    application_repository.get_by_job_and_candidate.return_value = (
        Application(
            id=uuid4(),
            organization_id=organization_id,
            job_id=job_id,
            candidate_id=candidate_id,
        )
    )

    with pytest.raises(
        ConflictError
    ) as error:
        asyncio.run(
            service.create(
                ApplicationCreate(
                    job_id=job_id,
                    candidate_id=candidate_id,
                ),
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert (
        error.value.code
        == "APPLICATION_ALREADY_EXISTS"
    )

    application_repository.create.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


def test_create_application_translates_duplicate_race() -> None:
    (
        service,
        session,
        application_repository,
        job_repository,
        candidate_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()
    candidate_id = uuid4()

    configure_valid_context(
        organization_id=organization_id,
        user_id=user_id,
        job_id=job_id,
        candidate_id=candidate_id,
        job_repository=job_repository,
        candidate_repository=candidate_repository,
        membership_repository=membership_repository,
    )

    duplicate = Application(
        id=uuid4(),
        organization_id=organization_id,
        job_id=job_id,
        candidate_id=candidate_id,
    )

    application_repository.get_by_job_and_candidate.side_effect = [
        None,
        duplicate,
    ]

    application_repository.create.side_effect = (
        IntegrityError(
            "INSERT",
            {},
            Exception(
                "unique constraint violation"
            ),
        )
    )

    with pytest.raises(
        ConflictError
    ) as error:
        asyncio.run(
            service.create(
                ApplicationCreate(
                    job_id=job_id,
                    candidate_id=candidate_id,
                ),
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert (
        error.value.code
        == "APPLICATION_ALREADY_EXISTS"
    )

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()

    assert (
        application_repository.get_by_job_and_candidate.await_count
        == 2
    )


def test_create_application_reraises_unrelated_integrity_error() -> None:
    (
        service,
        session,
        application_repository,
        job_repository,
        candidate_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()
    candidate_id = uuid4()

    configure_valid_context(
        organization_id=organization_id,
        user_id=user_id,
        job_id=job_id,
        candidate_id=candidate_id,
        job_repository=job_repository,
        candidate_repository=candidate_repository,
        membership_repository=membership_repository,
    )

    application_repository.get_by_job_and_candidate.side_effect = [
        None,
        None,
    ]

    database_error = IntegrityError(
        "INSERT",
        {},
        Exception(
            "unrelated integrity failure"
        ),
    )

    application_repository.create.side_effect = (
        database_error
    )

    with pytest.raises(
        IntegrityError
    ) as error:
        asyncio.run(
            service.create(
                ApplicationCreate(
                    job_id=job_id,
                    candidate_id=candidate_id,
                ),
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert error.value is database_error

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_list_applications_for_member() -> None:
    (
        service,
        session,
        application_repository,
        _job_repository,
        _candidate_repository,
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

    applications = [
        Application(
            id=uuid4(),
            organization_id=organization_id,
            job_id=uuid4(),
            candidate_id=uuid4(),
        )
    ]

    application_repository.list_for_organization.return_value = (
        applications
    )

    result = asyncio.run(
        service.list_for_user(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    assert result == applications

    application_repository.list_for_organization.assert_awaited_once_with(
        organization_id
    )

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


def test_list_applications_hides_organization_from_non_member() -> None:
    (
        service,
        _session,
        application_repository,
        _job_repository,
        _candidate_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = (
        None
    )

    with pytest.raises(
        NotFoundError
    ) as error:
        asyncio.run(
            service.list_for_user(
                organization_id=organization_id,
                user_id=uuid4(),
            )
        )

    assert (
        error.value.code
        == "ORGANIZATION_NOT_FOUND"
    )

    application_repository.list_for_organization.assert_not_awaited()


def test_get_application_for_member() -> None:
    (
        service,
        _session,
        application_repository,
        _job_repository,
        _candidate_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()
    application_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = (
        OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    application = Application(
        id=application_id,
        organization_id=organization_id,
        job_id=uuid4(),
        candidate_id=uuid4(),
    )

    application_repository.get_for_organization.return_value = (
        application
    )

    result = asyncio.run(
        service.get_for_user(
            application_id,
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    assert result is application


def test_get_application_returns_not_found() -> None:
    (
        service,
        _session,
        application_repository,
        _job_repository,
        _candidate_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()
    application_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = (
        OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    application_repository.get_for_organization.return_value = (
        None
    )

    with pytest.raises(
        NotFoundError
    ) as error:
        asyncio.run(
            service.get_for_user(
                application_id,
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert (
        error.value.code
        == "APPLICATION_NOT_FOUND"
    )

    assert error.value.details == {
        "organization_id": str(
            organization_id
        ),
        "application_id": str(
            application_id
        ),
    }
