import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.repositories.organization import OrganizationRepository


def test_create_adds_and_flushes_organization_without_committing() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()

    repository = OrganizationRepository(session)

    organization = asyncio.run(
        repository.create(
            name="Acme Corporation",
            slug="acme",
        )
    )

    assert organization.name == "Acme Corporation"
    assert organization.slug == "acme"

    session.add.assert_called_once_with(organization)
    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(organization)
    session.commit.assert_not_awaited()


def test_get_by_id_uses_session_get() -> None:
    organization_id = uuid4()

    expected_organization = Organization(
        name="Acme Corporation",
        slug="acme",
    )

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(
        return_value=expected_organization,
    )

    repository = OrganizationRepository(session)

    organization = asyncio.run(
        repository.get_by_id(organization_id)
    )

    assert organization is expected_organization

    session.get.assert_awaited_once_with(
        Organization,
        organization_id,
    )


def test_get_by_slug_returns_matching_organization() -> None:
    expected_organization = Organization(
        name="Acme Corporation",
        slug="acme",
    )

    result = MagicMock()
    result.scalar_one_or_none.return_value = expected_organization

    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(
        return_value=result,
    )

    repository = OrganizationRepository(session)

    organization = asyncio.run(
        repository.get_by_slug("acme")
    )

    assert organization is expected_organization

    session.execute.assert_awaited_once()
    result.scalar_one_or_none.assert_called_once_with()
