from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.job import Job
from app.repositories.job import JobRepository
from app.repositories.organization_membership import (
    OrganizationMembershipRepository,
)
from app.schemas.job import JobCreate, JobUpdate


class JobService:
    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

        self._repository = JobRepository(
            session
        )

        self._membership_repository = (
            OrganizationMembershipRepository(
                session
            )
        )

    async def create(
        self,
        data: JobCreate,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> Job:
        await self._require_membership(
            organization_id=organization_id,
            user_id=user_id,
        )

        try:
            job = await self._repository.create(
                organization_id=organization_id,
                title=data.title,
                description=data.description,
                status=data.status,
            )

            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        return job

    async def update_for_user(
        self,
        job_id: UUID,
        data: JobUpdate,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> Job:
        job = await self._get_job_for_user(
            job_id=job_id,
            organization_id=organization_id,
            user_id=user_id,
        )

        changes = data.model_dump(
            exclude_unset=True
        )

        try:
            updated_job = await self._repository.update(
                job,
                title=changes.get(
                    "title"
                ),
                description=changes.get(
                    "description"
                ),
                status=changes.get(
                    "status"
                ),
            )

            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        return updated_job

    async def list_for_user(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> list[Job]:
        await self._require_membership(
            organization_id=organization_id,
            user_id=user_id,
        )

        return await self._repository.list_for_organization(
            organization_id
        )

    async def get_for_user(
        self,
        job_id: UUID,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> Job:
        return await self._get_job_for_user(
            job_id=job_id,
            organization_id=organization_id,
            user_id=user_id,
        )

    async def _get_job_for_user(
        self,
        *,
        job_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> Job:
        await self._require_membership(
            organization_id=organization_id,
            user_id=user_id,
        )

        job = await self._repository.get_for_organization(
            job_id=job_id,
            organization_id=organization_id,
        )

        if job is None:
            raise self._job_not_found_error(
                organization_id=organization_id,
                job_id=job_id,
            )

        return job

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
    def _job_not_found_error(
        *,
        organization_id: UUID,
        job_id: UUID,
    ) -> NotFoundError:
        return NotFoundError(
            code="JOB_NOT_FOUND",
            message="Job was not found.",
            details={
                "organization_id": str(
                    organization_id
                ),
                "job_id": str(
                    job_id
                ),
            },
        )
