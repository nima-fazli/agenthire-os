from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization_membership import OrganizationMembership


class OrganizationMembershipRepository:
    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def create(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        role: str = "recruiter",
    ) -> OrganizationMembership:
        membership = OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
            role=role,
        )

        self._session.add(
            membership
        )

        await self._session.flush()
        await self._session.refresh(
            membership
        )

        return membership

    async def get_by_user_and_organization(
        self,
        *,
        user_id: UUID,
        organization_id: UUID,
    ) -> OrganizationMembership | None:
        statement = select(
            OrganizationMembership
        ).where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id
            == organization_id,
        )

        result = await self._session.execute(
            statement
        )

        return result.scalar_one_or_none()
