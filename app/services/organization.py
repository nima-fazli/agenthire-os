from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models.organization import Organization
from app.repositories.organization import OrganizationRepository
from app.repositories.organization_membership import (
    OrganizationMembershipRepository,
)
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
        self._membership_repository = (
            OrganizationMembershipRepository(
                session
            )
        )

    async def create(
        self,
        data: OrganizationCreate,
        *,
        owner_user_id: UUID,
    ) -> Organization:
        existing = await self._repository.get_by_slug(
            data.slug
        )

        if existing is not None:
            raise self._duplicate_slug_error(
                data.slug
            )

        try:
            organization = await self._repository.create(
                name=data.name,
                slug=data.slug,
            )

            await self._membership_repository.create(
                organization_id=organization.id,
                user_id=owner_user_id,
            )

            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()

            existing = await self._repository.get_by_slug(
                data.slug
            )

            if existing is not None:
                raise self._duplicate_slug_error(
                    data.slug
                ) from error

            raise
        except Exception:
            await self._session.rollback()
            raise

        return organization

    async def get_by_id(
        self,
        organization_id: UUID,
    ) -> Organization:
        organization = await self._repository.get_by_id(
            organization_id
        )

        if organization is None:
            raise NotFoundError(
                code="ORGANIZATION_NOT_FOUND",
                message="Organization was not found.",
                details={
                    "organization_id": str(
                        organization_id
                    ),
                },
            )

        return organization

    @staticmethod
    def _duplicate_slug_error(
        slug: str,
    ) -> ConflictError:
        return ConflictError(
            code="ORGANIZATION_SLUG_ALREADY_EXISTS",
            message="Organization slug already exists.",
            details={
                "slug": slug,
            },
        )
