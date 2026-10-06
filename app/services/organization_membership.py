from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.models.organization_membership import OrganizationMembership
from app.repositories.organization_membership import (
    OrganizationMembershipRepository,
)


class OrganizationMembershipService:
    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session
        self._repository = OrganizationMembershipRepository(
            session
        )

    async def create(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> OrganizationMembership:
        existing = await self._repository.get_by_user_and_organization(
            user_id=user_id,
            organization_id=organization_id,
        )

        if existing is not None:
            raise self._duplicate_membership_error(
                organization_id=organization_id,
                user_id=user_id,
            )

        try:
            membership = await self._repository.create(
                organization_id=organization_id,
                user_id=user_id,
            )

            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()

            existing = await self._repository.get_by_user_and_organization(
                user_id=user_id,
                organization_id=organization_id,
            )

            if existing is not None:
                raise self._duplicate_membership_error(
                    organization_id=organization_id,
                    user_id=user_id,
                ) from error

            raise
        except Exception:
            await self._session.rollback()
            raise

        return membership

    async def get_by_user_and_organization(
        self,
        *,
        user_id: UUID,
        organization_id: UUID,
    ) -> OrganizationMembership | None:
        return await self._repository.get_by_user_and_organization(
            user_id=user_id,
            organization_id=organization_id,
        )

    @staticmethod
    def _duplicate_membership_error(
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> ConflictError:
        return ConflictError(
            code="ORGANIZATION_MEMBERSHIP_ALREADY_EXISTS",
            message="User is already a member of this organization.",
            details={
                "organization_id": str(
                    organization_id
                ),
                "user_id": str(
                    user_id
                ),
            },
        )
