import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization_membership import (
    OrganizationMembership,
)
from app.repositories.organization_membership import (
    OrganizationMembershipRepository,
)


def test_create_membership_flushes_and_refreshes_without_commit() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()

    organization_id = uuid4()
    user_id = uuid4()

    repository = OrganizationMembershipRepository(
        session
    )

    membership = asyncio.run(
        repository.create(
            organization_id=organization_id,
            user_id=user_id,
        )
    )

    assert membership.organization_id == organization_id
    assert membership.user_id == user_id

    session.add.assert_called_once_with(
        membership
    )
    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(
        membership
    )

    session.commit.assert_not_awaited()


def test_get_by_user_and_organization_returns_membership() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.execute = AsyncMock()

    organization_id = uuid4()
    user_id = uuid4()

    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user_id,
    )

    result = MagicMock()
    result.scalar_one_or_none.return_value = membership

    session.execute.return_value = result

    repository = OrganizationMembershipRepository(
        session
    )

    returned_membership = asyncio.run(
        repository.get_by_user_and_organization(
            user_id=user_id,
            organization_id=organization_id,
        )
    )

    assert returned_membership is membership

    session.execute.assert_awaited_once()

    statement = session.execute.await_args.args[0]

    statement_text = str(statement)

    assert "organization_memberships.user_id" in statement_text
    assert (
        "organization_memberships.organization_id"
        in statement_text
    )

    parameters = set(
        statement.compile().params.values()
    )

    assert parameters == {
        user_id,
        organization_id,
    }


def test_get_by_user_and_organization_returns_none() -> None:
    session = MagicMock(
        spec=AsyncSession
    )
    session.execute = AsyncMock()

    result = MagicMock()
    result.scalar_one_or_none.return_value = None

    session.execute.return_value = result

    repository = OrganizationMembershipRepository(
        session
    )

    membership = asyncio.run(
        repository.get_by_user_and_organization(
            user_id=uuid4(),
            organization_id=uuid4(),
        )
    )

    assert membership is None

    session.execute.assert_awaited_once()
