import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.repositories.organization import OrganizationRepository
from app.repositories.organization_membership import (
    OrganizationMembershipRepository,
)
from app.schemas.organization import OrganizationCreate
from app.services.organization import OrganizationService


def test_create_organization_creates_owner_membership_and_commits() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    organization_repository = MagicMock(
        spec=OrganizationRepository
    )
    membership_repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    organization_id = uuid4()
    owner_user_id = uuid4()

    organization_repository.get_by_slug.return_value = None

    organization = Organization(
        id=organization_id,
        name="Acme",
        slug="acme",
    )

    organization_repository.create.return_value = organization

    service = OrganizationService(
        session
    )
    service._repository = organization_repository
    service._membership_repository = membership_repository

    result = asyncio.run(
        service.create(
            OrganizationCreate(
                name="Acme",
                slug="acme",
            ),
            owner_user_id=owner_user_id,
        )
    )

    assert result is organization

    organization_repository.get_by_slug.assert_awaited_once_with(
        "acme"
    )

    organization_repository.create.assert_awaited_once_with(
        name="Acme",
        slug="acme",
    )

    membership_repository.create.assert_awaited_once_with(
        organization_id=organization_id,
        user_id=owner_user_id,
    )

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


def test_create_organization_rejects_duplicate_slug() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    organization_repository = MagicMock(
        spec=OrganizationRepository
    )
    membership_repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    organization_repository.get_by_slug.return_value = Organization(
        id=uuid4(),
        name="Existing",
        slug="acme",
    )

    service = OrganizationService(
        session
    )
    service._repository = organization_repository
    service._membership_repository = membership_repository

    with pytest.raises(
        ConflictError
    ) as error:
        asyncio.run(
            service.create(
                OrganizationCreate(
                    name="Acme",
                    slug="acme",
                ),
                owner_user_id=uuid4(),
            )
        )

    assert error.value.status_code == 409
    assert (
        error.value.code
        == "ORGANIZATION_SLUG_ALREADY_EXISTS"
    )
    assert error.value.details == {
        "slug": "acme",
    }

    organization_repository.create.assert_not_awaited()
    membership_repository.create.assert_not_awaited()

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


def test_create_organization_handles_concurrent_duplicate_slug() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    organization_repository = MagicMock(
        spec=OrganizationRepository
    )
    membership_repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    existing = Organization(
        id=uuid4(),
        name="Existing",
        slug="acme",
    )

    organization_repository.get_by_slug.side_effect = [
        None,
        existing,
    ]

    organization_repository.create.side_effect = IntegrityError(
        "INSERT INTO organizations ...",
        {},
        Exception("duplicate key"),
    )

    service = OrganizationService(
        session
    )
    service._repository = organization_repository
    service._membership_repository = membership_repository

    with pytest.raises(
        ConflictError
    ) as error:
        asyncio.run(
            service.create(
                OrganizationCreate(
                    name="Acme",
                    slug="acme",
                ),
                owner_user_id=uuid4(),
            )
        )

    assert (
        error.value.code
        == "ORGANIZATION_SLUG_ALREADY_EXISTS"
    )

    membership_repository.create.assert_not_awaited()

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_create_organization_reraises_unrelated_integrity_error() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    organization_repository = MagicMock(
        spec=OrganizationRepository
    )
    membership_repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    integrity_error = IntegrityError(
        "INSERT INTO organizations ...",
        {},
        Exception("different integrity failure"),
    )

    organization_repository.get_by_slug.side_effect = [
        None,
        None,
    ]

    organization_repository.create.side_effect = integrity_error

    service = OrganizationService(
        session
    )
    service._repository = organization_repository
    service._membership_repository = membership_repository

    with pytest.raises(
        IntegrityError
    ) as error:
        asyncio.run(
            service.create(
                OrganizationCreate(
                    name="Acme",
                    slug="acme",
                ),
                owner_user_id=uuid4(),
            )
        )

    assert error.value is integrity_error

    membership_repository.create.assert_not_awaited()

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_create_organization_rolls_back_when_membership_creation_fails() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    organization_repository = MagicMock(
        spec=OrganizationRepository
    )
    membership_repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    organization = Organization(
        id=uuid4(),
        name="Acme",
        slug="acme",
    )

    organization_repository.get_by_slug.return_value = None
    organization_repository.create.return_value = organization

    failure = RuntimeError(
        "membership creation failed"
    )

    membership_repository.create.side_effect = failure

    service = OrganizationService(
        session
    )
    service._repository = organization_repository
    service._membership_repository = membership_repository

    with pytest.raises(
        RuntimeError
    ) as error:
        asyncio.run(
            service.create(
                OrganizationCreate(
                    name="Acme",
                    slug="acme",
                ),
                owner_user_id=uuid4(),
            )
        )

    assert error.value is failure

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_list_organizations_for_user_returns_repository_result() -> None:
    session = MagicMock(
        spec=AsyncSession
    )

    organization_repository = MagicMock(
        spec=OrganizationRepository
    )

    user_id = uuid4()

    organizations = [
        Organization(
            id=uuid4(),
            name="Acme",
            slug="acme",
        ),
        Organization(
            id=uuid4(),
            name="Example",
            slug="example",
        ),
    ]

    organization_repository.list_for_user.return_value = organizations

    service = OrganizationService(
        session
    )
    service._repository = organization_repository

    result = asyncio.run(
        service.list_for_user(
            user_id=user_id,
        )
    )

    assert result == organizations

    organization_repository.list_for_user.assert_awaited_once_with(
        user_id
    )


def test_get_organization_for_member_returns_organization() -> None:
    session = MagicMock(
        spec=AsyncSession
    )

    organization_repository = MagicMock(
        spec=OrganizationRepository
    )
    membership_repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    organization_id = uuid4()
    user_id = uuid4()

    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user_id,
    )

    organization = Organization(
        id=organization_id,
        name="Acme",
        slug="acme",
    )

    membership_repository.get_by_user_and_organization.return_value = (
        membership
    )
    organization_repository.get_by_id.return_value = organization

    service = OrganizationService(
        session
    )
    service._repository = organization_repository
    service._membership_repository = membership_repository

    result = asyncio.run(
        service.get_for_user(
            organization_id,
            user_id=user_id,
        )
    )

    assert result is organization

    membership_repository.get_by_user_and_organization.assert_awaited_once_with(
        user_id=user_id,
        organization_id=organization_id,
    )

    organization_repository.get_by_id.assert_awaited_once_with(
        organization_id
    )


def test_get_organization_hides_organization_from_non_member() -> None:
    session = MagicMock(
        spec=AsyncSession
    )

    organization_repository = MagicMock(
        spec=OrganizationRepository
    )
    membership_repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    organization_id = uuid4()
    user_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = None

    service = OrganizationService(
        session
    )
    service._repository = organization_repository
    service._membership_repository = membership_repository

    with pytest.raises(
        NotFoundError
    ) as error:
        asyncio.run(
            service.get_for_user(
                organization_id,
                user_id=user_id,
            )
        )

    assert error.value.status_code == 404
    assert error.value.code == "ORGANIZATION_NOT_FOUND"
    assert error.value.details == {
        "organization_id": str(
            organization_id
        ),
    }

    organization_repository.get_by_id.assert_not_awaited()


def test_get_organization_returns_not_found_when_member_target_is_missing() -> None:
    session = MagicMock(
        spec=AsyncSession
    )

    organization_repository = MagicMock(
        spec=OrganizationRepository
    )
    membership_repository = MagicMock(
        spec=OrganizationMembershipRepository
    )

    organization_id = uuid4()
    user_id = uuid4()

    membership_repository.get_by_user_and_organization.return_value = (
        OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    organization_repository.get_by_id.return_value = None

    service = OrganizationService(
        session
    )
    service._repository = organization_repository
    service._membership_repository = membership_repository

    with pytest.raises(
        NotFoundError
    ) as error:
        asyncio.run(
            service.get_for_user(
                organization_id,
                user_id=user_id,
            )
        )

    assert error.value.status_code == 404
    assert error.value.code == "ORGANIZATION_NOT_FOUND"
    assert error.value.details == {
        "organization_id": str(
            organization_id
        ),
    }
