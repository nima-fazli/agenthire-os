import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.organization_membership import OrganizationMembership
from app.repositories.application import ApplicationRepository
from app.repositories.candidate import CandidateRepository
from app.repositories.job import JobRepository
from app.repositories.organization_membership import OrganizationMembershipRepository
from app.schemas.application import (
    ApplicationCreate,
    ApplicationStatus,
    ApplicationStatusTransition,
)
from app.services.application import ApplicationService


@pytest.fixture
def context():
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    repository = MagicMock(spec=ApplicationRepository)
    jobs = MagicMock(spec=JobRepository)
    candidates = MagicMock(spec=CandidateRepository)
    memberships = MagicMock(spec=OrganizationMembershipRepository)

    service = ApplicationService(session)
    service._repository = repository
    service._job_repository = jobs
    service._candidate_repository = candidates
    service._membership_repository = memberships

    now = datetime.now(UTC)
    application = Application(
        id=uuid4(),
        organization_id=uuid4(),
        job_id=uuid4(),
        candidate_id=uuid4(),
        status="applied",
        created_at=now,
        updated_at=now,
    )

    user_id = uuid4()

    memberships.get_by_user_and_organization.return_value = OrganizationMembership(
        organization_id=application.organization_id, user_id=user_id
    )

    jobs.get_for_organization.return_value = Job(
        id=application.job_id,
        organization_id=application.organization_id,
        title="AI Engineer",
        description="Build AI systems.",
        status="open",
    )

    candidates.get_for_organization.return_value = Candidate(
        id=application.candidate_id,
        organization_id=application.organization_id,
        full_name="Ada Lovelace",
    )

    repository.get_by_job_and_candidate.return_value = None
    repository.get_for_organization.return_value = application
    repository.create.return_value = application

    async def update_status(existing: Application, *, status: str) -> Application:
        existing.status = status
        return existing

    repository.update_status.side_effect = update_status

    return SimpleNamespace(
        service=service,
        session=session,
        repository=repository,
        jobs=jobs,
        candidates=candidates,
        memberships=memberships,
        application=application,
        user_id=user_id,
        organization_id=application.organization_id,
    )


def create_application(context):
    return asyncio.run(
        context.service.create(
            ApplicationCreate(
                job_id=context.application.job_id,
                candidate_id=context.application.candidate_id,
            ),
            organization_id=context.organization_id,
            user_id=context.user_id,
        )
    )


def transition(context, status: str):
    return asyncio.run(
        context.service.transition_status_for_user(
            context.application.id,
            ApplicationStatusTransition(status=status),
            organization_id=context.organization_id,
            user_id=context.user_id,
        )
    )


def test_create_application_for_valid_tenant_commits(context) -> None:
    assert create_application(context) is context.application

    context.repository.create.assert_awaited_once_with(
        organization_id=context.organization_id,
        job_id=context.application.job_id,
        candidate_id=context.application.candidate_id,
    )
    context.session.commit.assert_awaited_once()
    context.session.rollback.assert_not_awaited()


def test_create_application_hides_organization_from_non_member(context) -> None:
    context.memberships.get_by_user_and_organization.return_value = None

    with pytest.raises(NotFoundError) as error:
        create_application(context)

    assert error.value.code == "ORGANIZATION_NOT_FOUND"
    context.jobs.get_for_organization.assert_not_awaited()
    context.candidates.get_for_organization.assert_not_awaited()
    context.repository.get_by_job_and_candidate.assert_not_awaited()
    context.repository.create.assert_not_awaited()
    context.session.commit.assert_not_awaited()
    context.session.rollback.assert_not_awaited()


def test_create_application_rejects_job_outside_tenant(context) -> None:
    context.jobs.get_for_organization.return_value = None

    with pytest.raises(NotFoundError) as error:
        create_application(context)

    assert error.value.code == "JOB_NOT_FOUND"
    context.candidates.get_for_organization.assert_not_awaited()
    context.repository.create.assert_not_awaited()
    context.session.commit.assert_not_awaited()
    context.session.rollback.assert_not_awaited()


def test_create_application_rejects_candidate_outside_tenant(context) -> None:
    context.candidates.get_for_organization.return_value = None

    with pytest.raises(NotFoundError) as error:
        create_application(context)

    assert error.value.code == "CANDIDATE_NOT_FOUND"
    context.repository.create.assert_not_awaited()
    context.session.commit.assert_not_awaited()
    context.session.rollback.assert_not_awaited()


def test_create_application_rejects_existing_pair(context) -> None:
    context.repository.get_by_job_and_candidate.return_value = context.application

    with pytest.raises(ConflictError) as error:
        create_application(context)

    assert error.value.code == "APPLICATION_ALREADY_EXISTS"
    context.repository.create.assert_not_awaited()
    context.session.commit.assert_not_awaited()
    context.session.rollback.assert_not_awaited()


def test_create_application_translates_duplicate_race(context) -> None:
    context.repository.get_by_job_and_candidate.side_effect = [None, context.application]

    database_error = IntegrityError(
        "INSERT", {}, RuntimeError("unique constraint violation")
    )
    context.repository.create.side_effect = database_error

    events = MagicMock()
    events.attach_mock(context.repository.get_by_job_and_candidate, "lookup")
    events.attach_mock(context.repository.create, "create")
    events.attach_mock(context.session.rollback, "rollback")

    with pytest.raises(ConflictError) as error:
        create_application(context)

    assert error.value.code == "APPLICATION_ALREADY_EXISTS"
    assert error.value.__cause__ is database_error
    assert [item[0] for item in events.mock_calls] == [
        "lookup", "create", "rollback", "lookup"
    ]
    context.session.rollback.assert_awaited_once()
    context.session.commit.assert_not_awaited()


def test_create_application_reraises_unrelated_integrity_error(context) -> None:
    context.repository.get_by_job_and_candidate.side_effect = [None, None]

    failure = IntegrityError(
        "INSERT", {}, RuntimeError("unrelated integrity failure")
    )
    context.repository.create.side_effect = failure

    with pytest.raises(IntegrityError) as error:
        create_application(context)

    assert error.value is failure
    assert context.repository.get_by_job_and_candidate.await_count == 2
    context.session.rollback.assert_awaited_once()
    context.session.commit.assert_not_awaited()


def test_list_applications_for_member(context) -> None:
    context.repository.list_for_organization.return_value = [context.application]

    result = asyncio.run(
        context.service.list_for_user(
            organization_id=context.organization_id, user_id=context.user_id
        )
    )

    assert result == [context.application]
    context.repository.list_for_organization.assert_awaited_once_with(
        context.organization_id
    )
    context.session.commit.assert_not_awaited()
    context.session.rollback.assert_not_awaited()


def test_list_applications_hides_organization_from_non_member(context) -> None:
    context.memberships.get_by_user_and_organization.return_value = None

    with pytest.raises(NotFoundError) as error:
        asyncio.run(
            context.service.list_for_user(
                organization_id=context.organization_id, user_id=context.user_id
            )
        )

    assert error.value.code == "ORGANIZATION_NOT_FOUND"
    context.repository.list_for_organization.assert_not_awaited()


def test_get_application_for_member(context) -> None:
    result = asyncio.run(
        context.service.get_for_user(
            context.application.id,
            organization_id=context.organization_id,
            user_id=context.user_id,
        )
    )

    assert result is context.application
    context.repository.get_for_organization.assert_awaited_once_with(
        application_id=context.application.id,
        organization_id=context.organization_id,
    )


def test_get_application_returns_not_found(context) -> None:
    context.repository.get_for_organization.return_value = None

    with pytest.raises(NotFoundError) as error:
        asyncio.run(
            context.service.get_for_user(
                context.application.id,
                organization_id=context.organization_id,
                user_id=context.user_id,
            )
        )

    assert error.value.code == "APPLICATION_NOT_FOUND"
    assert error.value.details == {
        "organization_id": str(context.organization_id),
        "application_id": str(context.application.id),
    }


# Product rules, independent of the Service's implementation map.
VALID_TRANSITIONS = [
    ("applied", "screening"),
    ("screening", "interview"),
    ("interview", "offer"),
    ("offer", "hired"),
    ("applied", "rejected"),
    ("screening", "rejected"),
    ("interview", "rejected"),
    ("offer", "rejected"),
]

INVALID_TRANSITIONS = [
    (current.value, requested.value)
    for current in ApplicationStatus
    for requested in ApplicationStatus
    if current != requested
    and (current.value, requested.value) not in VALID_TRANSITIONS
]


@pytest.mark.parametrize(("current", "requested"), VALID_TRANSITIONS)
def test_transition_commits_valid_forward_or_rejection_move(
    context, current, requested
) -> None:
    context.application.status = current

    events = MagicMock()
    events.attach_mock(context.memberships.get_by_user_and_organization, "membership")
    events.attach_mock(context.repository.get_for_organization, "lookup")
    events.attach_mock(context.repository.update_status, "update")
    events.attach_mock(context.session.commit, "commit")

    result = transition(context, requested)

    assert result is context.application
    assert result.status == requested
    assert events.mock_calls == [
        call.membership(
            user_id=context.user_id, organization_id=context.organization_id
        ),
        call.lookup(
            application_id=context.application.id,
            organization_id=context.organization_id,
            for_update=True,
        ),
        call.update(context.application, status=requested),
        call.commit(),
    ]
    context.session.rollback.assert_not_awaited()


@pytest.mark.parametrize("status", [item.value for item in ApplicationStatus])
def test_same_state_transition_is_idempotent_and_releases_lock(context, status) -> None:
    context.application.status = status
    original_updated_at = context.application.updated_at

    result = transition(context, status)

    assert result is context.application
    assert result.status == status
    assert result.updated_at == original_updated_at
    context.repository.update_status.assert_not_awaited()
    context.session.commit.assert_awaited_once()
    context.session.rollback.assert_not_awaited()


@pytest.mark.parametrize(("current", "requested"), INVALID_TRANSITIONS)
def test_transition_rejects_skips_backwards_and_terminal_changes(
    context, current, requested
) -> None:
    context.application.status = current

    with pytest.raises(ConflictError) as error:
        transition(context, requested)

    assert error.value.code == "INVALID_APPLICATION_STATUS_TRANSITION"
    assert error.value.details == {
        "current_status": current,
        "requested_status": requested,
        "allowed_statuses": sorted(
            target for source, target in VALID_TRANSITIONS if source == current
        ),
    }
    assert context.application.status == current
    context.repository.update_status.assert_not_awaited()
    context.session.commit.assert_not_awaited()
    context.session.rollback.assert_awaited_once()


def test_transition_checks_membership_before_sensitive_lookup(context) -> None:
    context.memberships.get_by_user_and_organization.return_value = None

    with pytest.raises(NotFoundError) as error:
        transition(context, "screening")

    assert error.value.code == "ORGANIZATION_NOT_FOUND"
    context.repository.get_for_organization.assert_not_awaited()
    context.repository.update_status.assert_not_awaited()
    context.session.commit.assert_not_awaited()
    context.session.rollback.assert_not_awaited()


def test_transition_rejects_application_absent_from_requested_tenant(context) -> None:
    context.repository.get_for_organization.return_value = None

    with pytest.raises(NotFoundError) as error:
        transition(context, "screening")

    assert error.value.code == "APPLICATION_NOT_FOUND"
    assert error.value.details == {
        "organization_id": str(context.organization_id),
        "application_id": str(context.application.id),
    }
    context.repository.get_for_organization.assert_awaited_once_with(
        application_id=context.application.id,
        organization_id=context.organization_id,
        for_update=True,
    )
    context.repository.update_status.assert_not_awaited()
    context.session.commit.assert_not_awaited()
    context.session.rollback.assert_awaited_once()


@pytest.mark.parametrize("failure_point", ["lookup", "update", "commit"])
def test_transition_rolls_back_database_failures(context, failure_point) -> None:
    failure = RuntimeError("Synthetic transaction failure")

    operation = {
        "lookup": context.repository.get_for_organization,
        "update": context.repository.update_status,
        "commit": context.session.commit,
    }[failure_point]
    operation.side_effect = failure

    with pytest.raises(RuntimeError) as error:
        transition(context, "screening")

    assert error.value is failure
    context.session.rollback.assert_awaited_once()

    if failure_point != "commit":
        context.session.commit.assert_not_awaited()

    if failure_point == "lookup":
        context.repository.update_status.assert_not_awaited()
