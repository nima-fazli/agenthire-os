from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.candidate import Candidate
from app.repositories.candidate import CandidateRepository
from app.repositories.organization_membership import (
    OrganizationMembershipRepository,
)
from app.schemas.candidate import CandidateCreate, CandidateUpdate


class CandidateService:
    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

        self._repository = CandidateRepository(
            session
        )

        self._membership_repository = (
            OrganizationMembershipRepository(
                session
            )
        )

    async def create(
        self,
        data: CandidateCreate,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> Candidate:
        await self._require_membership(
            organization_id=organization_id,
            user_id=user_id,
        )

        try:
            candidate = await self._repository.create(
                organization_id=organization_id,
                full_name=data.full_name,
                email=data.email,
                phone=data.phone,
                location=data.location,
                headline=data.headline,
                summary=data.summary,
            )

            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        return candidate

    async def update_for_user(
        self,
        candidate_id: UUID,
        data: CandidateUpdate,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> Candidate:
        candidate = await self._get_candidate_for_user(
            candidate_id=candidate_id,
            organization_id=organization_id,
            user_id=user_id,
        )

        changes = data.model_dump(
            exclude_unset=True
        )

        try:
            updated_candidate = (
                await self._repository.update(
                    candidate,
                    full_name=changes.get(
                        "full_name"
                    ),
                    email=changes.get(
                        "email"
                    ),
                    phone=changes.get(
                        "phone"
                    ),
                    location=changes.get(
                        "location"
                    ),
                    headline=changes.get(
                        "headline"
                    ),
                    summary=changes.get(
                        "summary"
                    ),
                )
            )

            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        return updated_candidate

    async def list_for_user(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> list[Candidate]:
        await self._require_membership(
            organization_id=organization_id,
            user_id=user_id,
        )

        return await self._repository.list_for_organization(
            organization_id
        )

    async def get_for_user(
        self,
        candidate_id: UUID,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> Candidate:
        return await self._get_candidate_for_user(
            candidate_id=candidate_id,
            organization_id=organization_id,
            user_id=user_id,
        )

    async def _get_candidate_for_user(
        self,
        *,
        candidate_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> Candidate:
        await self._require_membership(
            organization_id=organization_id,
            user_id=user_id,
        )

        candidate = await self._repository.get_for_organization(
            candidate_id=candidate_id,
            organization_id=organization_id,
        )

        if candidate is None:
            raise self._candidate_not_found_error(
                organization_id=organization_id,
                candidate_id=candidate_id,
            )

        return candidate

    async def _require_membership(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> None:
        membership = (
            await self._membership_repository.get_by_user_and_organization(
                user_id=user_id,
                organization_id=organization_id,
            )
        )

        if membership is None:
            raise NotFoundError(
                code="ORGANIZATION_NOT_FOUND",
                message="Organization was not found.",
                details={
                    "organization_id": str(
                        organization_id
                    ),
                },
            )

    @staticmethod
    def _candidate_not_found_error(
        *,
        organization_id: UUID,
        candidate_id: UUID,
    ) -> NotFoundError:
        return NotFoundError(
            code="CANDIDATE_NOT_FOUND",
            message="Candidate was not found.",
            details={
                "organization_id": str(
                    organization_id
                ),
                "candidate_id": str(
                    candidate_id
                ),
            },
        )
