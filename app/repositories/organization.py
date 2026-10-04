from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        name: str,
        slug: str,
    ) -> Organization:
        organization = Organization(
            name=name,
            slug=slug,
        )

        self._session.add(organization)

        await self._session.flush()
        await self._session.refresh(organization)

        return organization

    async def get_by_id(
        self,
        organization_id: UUID,
    ) -> Organization | None:
        return await self._session.get(
            Organization,
            organization_id,
        )

    async def get_by_slug(
        self,
        slug: str,
    ) -> Organization | None:
        statement = select(Organization).where(
            Organization.slug == slug
        )

        result = await self._session.execute(statement)

        return result.scalar_one_or_none()
