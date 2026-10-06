import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.repositories.organization import OrganizationRepository


def test_create_organization_flushes_and_refreshes_without_commit() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()

    repository = OrganizationRepository(
        session
    )

    organization = asyncio.run(
        repository.create(
            name="Acme",
            slug="acme",
        )
    )

    assert organization.name == "Acme"
    assert organization.slug == "acme"

    session.add.assert_called_once_with(
        organization
    )
    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(
        organization
    )

    session.commit.assert_not_awaited()


def test_get_organization_by_id() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.get = AsyncMock()

    organization_id = uuid4()

    organization = Organization(
        id=organization_id,
        name="Acme",
        slug="acme",
    )

    session.get.return_value = organization

    repository = OrganizationRepository(
        session
    )

    result = asyncio.run(
        repository.get_by_id(
            organization_id
        )
    )

    assert result is organization

    session.get.assert_awaited_once_with(
        Organization,
        organization_id,
    )


def test_get_organization_by_slug() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.execute = AsyncMock()

    organization = Organization(
        id=uuid4(),
        name="Acme",
        slug="acme",
    )

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = organization

    session.execute.return_value = query_result

    repository = OrganizationRepository(
        session
    )

    result = asyncio.run(
        repository.get_by_slug(
            "acme"
        )
    )

    assert result is organization

    session.execute.assert_awaited_once()

    statement = session.execute.await_args.args[0]

    assert "organizations.slug" in str(
        statement
    )

    assert set(
        statement.compile().params.values()
    ) == {
        "acme",
    }


def test_list_organizations_for_user() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.execute = AsyncMock()

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

    scalar_result = MagicMock()
    scalar_result.all.return_value = organizations

    query_result = MagicMock()
    query_result.scalars.return_value = scalar_result

    session.execute.return_value = query_result

    repository = OrganizationRepository(
        session
    )

    result = asyncio.run(
        repository.list_for_user(
            user_id
        )
    )

    assert result == organizations

    session.execute.assert_awaited_once()

    statement = session.execute.await_args.args[0]
    statement_text = str(
        statement
    )

    assert "JOIN organization_memberships" in statement_text
    assert (
        "organization_memberships.user_id"
        in statement_text
    )

    assert set(
        statement.compile().params.values()
    ) == {
        user_id,
    }
