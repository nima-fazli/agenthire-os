import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.models.organization import Organization
from app.repositories.organization import OrganizationRepository
from app.schemas.organization import OrganizationCreate
from app.services.organization import OrganizationService


def test_create_organization_commits_transaction() -> None:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

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


def test_create_organization_rejects_duplicate_slug() -> None:
    session = MagicMock(spec=AsyncSession)

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
