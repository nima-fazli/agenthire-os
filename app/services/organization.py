from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.models.organization import Organization
from app.repositories.organization import OrganizationRepository
from app.schemas.organization import OrganizationCreate


class OrganizationService:
    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session
        self._repository = OrganizationRepository(
            session
        )

    async def create(
        self,
        data: OrganizationCreate,
    ) -> Organization:
        existing = await self._repository.get_by_slug(
            data.slug
        )

        if existing is not None:
            raise ConflictError(
                code="ORGANIZATION_SLUG_ALREADY_EXISTS",
                message="Organization slug already exists.",
                details={
                    "slug": data.slug,
                },
            )

        organization = await self._repository.create(
            name=data.name,
            slug=data.slug,
        )

        await self._session.commit()

        await self._session.refresh(
            organization
        )

        return organization
