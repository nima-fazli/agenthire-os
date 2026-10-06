import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.models.organization_membership import OrganizationMembership
from app.repositories.organization_membership import (
    OrganizationMembershipRepository,
)
from app.services.organization_membership import (
    OrganizationMembershipService,
)


def test_create_membership_commits() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    organization_id = uuid4()
    user_id = uuid4()

    repository.get_by_user_and_organization.return_value = None

    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user_id,
    )

    repository.create.return_value = membership

    service = OrganizationMembershipService(
        session
    )
    service._repository = repository

    result = asyncio.run(
        service.create(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    assert result is membership

    repository.get_by_user_and_organization.assert_awaited_once_with(
        user_id=user_id,
        organization_id=organization_id,
    )

    repository.create.assert_awaited_once_with(
        organization_id=organization_id,
        user_id=user_id,
    )

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


def test_create_membership_rejects_existing_membership() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    organization_id = uuid4()
    user_id = uuid4()

    repository.get_by_user_and_organization.return_value = (
        OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    service = OrganizationMembershipService(
        session
    )
    service._repository = repository

    with pytest.raises(
        ConflictError
    ) as error:
        asyncio.run(
            service.create(
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert error.value.status_code == 409
    assert (
        error.value.code
        == "ORGANIZATION_MEMBERSHIP_ALREADY_EXISTS"
    )
    assert error.value.details == {
        "organization_id": str(
            organization_id
        ),
        "user_id": str(
            user_id
        ),
    }

    repository.create.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


def test_create_membership_handles_concurrent_duplicate() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    organization_id = uuid4()
    user_id = uuid4()

    existing_membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user_id,
    )

    repository.get_by_user_and_organization.side_effect = [
        None,
        existing_membership,
    ]

    repository.create.side_effect = IntegrityError(
        "INSERT INTO organization_memberships ...",
        {},
        Exception("duplicate key"),
    )

    service = OrganizationMembershipService(
        session
    )
    service._repository = repository

    with pytest.raises(
        ConflictError
    ) as error:
        asyncio.run(
            service.create(
                organization_id=organization_id,
                user_id=user_id,
            )
        )

    assert (
        error.value.code
        == "ORGANIZATION_MEMBERSHIP_ALREADY_EXISTS"
    )

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_create_membership_reraises_unrelated_integrity_error() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    integrity_error = IntegrityError(
        "INSERT INTO organization_memberships ...",
        {},
        Exception("different integrity failure"),
    )

    repository.get_by_user_and_organization.side_effect = [
        None,
        None,
    ]

    repository.create.side_effect = integrity_error

    service = OrganizationMembershipService(
        session
    )
    service._repository = repository

    with pytest.raises(
        IntegrityError
    ) as error:
        asyncio.run(
            service.create(
                organization_id=uuid4(),
                user_id=uuid4(),
            )
        )

    assert error.value is integrity_error

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_get_by_user_and_organization_returns_repository_result() -> None:
    session = MagicMock(
        spec=AsyncSession
    )

    repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    organization_id = uuid4()
    user_id = uuid4()

    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user_id,
    )

    repository.get_by_user_and_organization.return_value = membership

    service = OrganizationMembershipService(
        session
    )
    service._repository = repository

    result = asyncio.run(
        service.get_by_user_and_organization(
            user_id=user_id,
            organization_id=organization_id,
        )
    )

    assert result is membership

    repository.get_by_user_and_organization.assert_awaited_once_with(
        user_id=user_id,
        organization_id=organization_id,
    )
