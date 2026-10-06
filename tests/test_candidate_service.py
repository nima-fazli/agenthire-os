import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.candidate import Candidate
from app.models.organization_membership import (
    OrganizationMembership,
)
from app.repositories.candidate import CandidateRepository
from app.repositories.organization_membership import (
    OrganizationMembershipRepository,
)
from app.schemas.candidate import CandidateCreate
from app.services.candidate import CandidateService


def make_service() -> tuple[
    CandidateService,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    session = MagicMock(
        spec=AsyncSession
    )

    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    candidate_repository = MagicMock(
        spec=CandidateRepository
    )

    membership_repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    service = CandidateService(
        session
    )

    service._repository = (
        candidate_repository
    )
    service._membership_repository = (
        membership_repository
    )

    return (
        service,
        session,
        candidate_repository,
        membership_repository,
    )


def test_create_candidate_for_member_commits() -> None:
    (
        service,
        session,
        candidate_repository,
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

    candidate = Candidate(
        id=uuid4(),
        organization_id=organization_id,
        full_name="Ada Lovelace",
        email="ada@example.com",
        location="Amsterdam",
        headline="AI Engineer",
    )

    candidate_repository.create.return_value = (
        candidate
    )

    result = asyncio.run(
        service.create(
            CandidateCreate(
                full_name="Ada Lovelace",
                email="ada@example.com",
                location="Amsterdam",
                headline="AI Engineer",
            ),
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    assert result is candidate

    candidate_repository.create.assert_awaited_once_with(
        organization_id=organization_id,
        full_name="Ada Lovelace",
        email="ada@example.com",
        phone=None,
        location="Amsterdam",
        headline="AI Engineer",
        summary=None,
    )

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


def test_create_candidate_hides_organization_from_non_member() -> None:
    (
        service,
        session,
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
                CandidateCreate(
                    full_name="Ada Lovelace",
                ),
                organization_id=organization_id,
                user_id=uuid4(),
            )
        )

    assert (
        error.value.code
        == "ORGANIZATION_NOT_FOUND"
    )

    candidate_repository.create.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


def test_create_candidate_rolls_back_on_failure() -> None:
    (
        service,
        session,
        candidate_repository,
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

    candidate_repository.create.side_effect = RuntimeError(
        "database failure"
    )

    with pytest.raises(
        RuntimeError
    ):
        asyncio.run(
            service.create(
                CandidateCreate(
                    full_name="Ada Lovelace",
                ),
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


def test_list_candidates_for_member() -> None:
    (
        service,
        session,
        candidate_repository,
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

    candidates = [
        Candidate(
            id=uuid4(),
            organization_id=organization_id,
            full_name="Ada Lovelace",
        )
    ]

    candidate_repository.list_for_organization.return_value = (
        candidates
    )

    result = asyncio.run(
        service.list_for_user(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    assert result == candidates

    candidate_repository.list_for_organization.assert_awaited_once_with(
        organization_id
    )

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


def test_list_candidates_hides_organization_from_non_member() -> None:
    (
        service,
        _session,
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
            service.list_for_user(
                organization_id=organization_id,
                user_id=uuid4(),
            )
        )

    assert (
        error.value.code
        == "ORGANIZATION_NOT_FOUND"
    )

    candidate_repository.list_for_organization.assert_not_awaited()


def test_get_candidate_for_member() -> None:
    (
        service,
        _session,
        candidate_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()
    candidate_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = (
        OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    candidate = Candidate(
        id=candidate_id,
        organization_id=organization_id,
        full_name="Ada Lovelace",
    )

    candidate_repository.get_for_organization.return_value = (
        candidate
    )

    result = asyncio.run(
        service.get_for_user(
            candidate_id,
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    assert result is candidate

    candidate_repository.get_for_organization.assert_awaited_once_with(
        candidate_id=candidate_id,
        organization_id=organization_id,
    )


def test_get_candidate_returns_not_found() -> None:
    (
        service,
        _session,
        candidate_repository,
        membership_repository,
    ) = make_service()

    organization_id = uuid4()
    user_id = uuid4()
    candidate_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = (
        OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    candidate_repository.get_for_organization.return_value = (
        None
    )

    with pytest.raises(
        NotFoundError
    ) as error:
        asyncio.run(
            service.get_for_user(
                candidate_id,
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert (
        error.value.code
        == "CANDIDATE_NOT_FOUND"
    )

    assert error.value.details == {
        "organization_id": str(
            organization_id
        ),
        "candidate_id": str(
            candidate_id
        ),
    }
