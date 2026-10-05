import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.models.organization import Organization
from app.repositories.organization import OrganizationRepository
from app.schemas.organization import OrganizationCreate
from app.services.organization import OrganizationService


def test_create_organization_commits_transaction() -> None:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    repository = MagicMock(
        spec=OrganizationRepository
    )

    organization = Organization(
        name="Acme Corporation",
        slug="acme",
    )

    repository.get_by_slug.return_value = None
    repository.create.return_value = organization

    service = OrganizationService(session)

    service._repository = repository

    result = asyncio.run(
        service.create(
            OrganizationCreate(
                name="Acme Corporation",
                slug="acme",
            )
        )
    )

    assert result is organization

    repository.get_by_slug.assert_called_once_with(
        "acme"
    )

    repository.create.assert_called_once_with(
        name="Acme Corporation",
        slug="acme",
    )

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


def test_create_organization_rejects_duplicate_slug() -> None:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    repository = MagicMock(
        spec=OrganizationRepository
    )

    repository.get_by_slug.return_value = Organization(
        name="Existing",
        slug="acme",
    )

    service = OrganizationService(session)

    service._repository = repository

    with pytest.raises(ConflictError) as error:
        asyncio.run(
            service.create(
                OrganizationCreate(
                    name="Acme Corporation",
                    slug="acme",
                )
            )
        )

    assert (
        error.value.code
        == "ORGANIZATION_SLUG_ALREADY_EXISTS"
    )

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


def test_create_organization_handles_concurrent_duplicate() -> None:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    repository = MagicMock(
        spec=OrganizationRepository
    )

    concurrent_organization = Organization(
        name="Existing",
        slug="acme",
    )

    repository.get_by_slug.side_effect = [
        None,
        concurrent_organization,
    ]
    repository.create.side_effect = IntegrityError(
        "INSERT INTO organizations ...",
        {},
        Exception("duplicate key"),
    )

    service = OrganizationService(session)

    service._repository = repository

    with pytest.raises(ConflictError) as error:
        asyncio.run(
            service.create(
                OrganizationCreate(
                    name="Acme Corporation",
                    slug="acme",
                )
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

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_create_organization_reraises_unrelated_integrity_error() -> None:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    repository = MagicMock(
        spec=OrganizationRepository
    )

    integrity_error = IntegrityError(
        "INSERT INTO organizations ...",
        {},
        Exception("different integrity failure"),
    )

    repository.get_by_slug.side_effect = [
        None,
        None,
    ]
    repository.create.side_effect = integrity_error

    service = OrganizationService(session)

    service._repository = repository

    with pytest.raises(IntegrityError) as error:
        asyncio.run(
            service.create(
                OrganizationCreate(
                    name="Acme Corporation",
                    slug="acme",
                )
            )
        )

    assert error.value is integrity_error
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
