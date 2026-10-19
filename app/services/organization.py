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
                role="owner",
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

    async def list_for_user(
        self,
        *,
        user_id: UUID,
    ) -> list[Organization]:
        return await self._repository.list_for_user(
            user_id
        )

    async def get_for_user(
        self,
        organization_id: UUID,
        *,
        user_id: UUID,
    ) -> Organization:
        membership = (
            await self._membership_repository.get_by_user_and_organization(
                user_id=user_id,
                organization_id=organization_id,
            )
        )

        if membership is None:
            raise self._organization_not_found_error(
                organization_id
            )

        organization = await self._repository.get_by_id(
            organization_id
        )

        if organization is None:
            raise self._organization_not_found_error(
                organization_id
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

    @staticmethod
    def _organization_not_found_error(
        organization_id: UUID,
    ) -> NotFoundError:
        return NotFoundError(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization was not found.",
            details={
                "organization_id": str(
                    organization_id
                ),
            },
        )
