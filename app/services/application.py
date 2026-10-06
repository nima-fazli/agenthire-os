from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models.application import Application
from app.repositories.application import ApplicationRepository
from app.repositories.candidate import CandidateRepository
from app.repositories.job import JobRepository
from app.repositories.organization_membership import (
    OrganizationMembershipRepository,
)
from app.schemas.application import ApplicationCreate


class ApplicationService:
    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

        self._repository = ApplicationRepository(
            session
        )

        self._job_repository = JobRepository(
            session
        )

        self._candidate_repository = (
            CandidateRepository(
                session
            )
        )

        self._membership_repository = (
            OrganizationMembershipRepository(
                session
            )
        )

    async def create(
        self,
        data: ApplicationCreate,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> Application:
        await self._require_membership(
            organization_id=organization_id,
            user_id=user_id,
        )

        job = await self._job_repository.get_for_organization(
            job_id=data.job_id,
            organization_id=organization_id,
        )

        if job is None:
            raise self._job_not_found_error(
                organization_id=organization_id,
                job_id=data.job_id,
            )

        candidate = (
            await self._candidate_repository.get_for_organization(
                candidate_id=data.candidate_id,
                organization_id=organization_id,
            )
        )

        if candidate is None:
            raise self._candidate_not_found_error(
                organization_id=organization_id,
                candidate_id=data.candidate_id,
            )

        existing = (
            await self._repository.get_by_job_and_candidate(
                organization_id=organization_id,
                job_id=data.job_id,
                candidate_id=data.candidate_id,
            )
        )

        if existing is not None:
            raise self._duplicate_application_error(
                organization_id=organization_id,
                job_id=data.job_id,
                candidate_id=data.candidate_id,
            )

        try:
            application = await self._repository.create(
                organization_id=organization_id,
                job_id=data.job_id,
                candidate_id=data.candidate_id,
            )

            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()

            existing = (
                await self._repository.get_by_job_and_candidate(
                    organization_id=organization_id,
                    job_id=data.job_id,
                    candidate_id=data.candidate_id,
                )
            )

            if existing is not None:
                raise self._duplicate_application_error(
                    organization_id=organization_id,
                    job_id=data.job_id,
                    candidate_id=data.candidate_id,
                ) from error

            raise
        except Exception:
            await self._session.rollback()
            raise

        return application

    async def list_for_user(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> list[Application]:
        await self._require_membership(
            organization_id=organization_id,
            user_id=user_id,
        )

        return await self._repository.list_for_organization(
            organization_id
        )

    async def get_for_user(
        self,
        application_id: UUID,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> Application:
        await self._require_membership(
            organization_id=organization_id,
            user_id=user_id,
        )

        application = (
            await self._repository.get_for_organization(
                application_id=application_id,
                organization_id=organization_id,
            )
        )

        if application is None:
            raise self._application_not_found_error(
                organization_id=organization_id,
                application_id=application_id,
            )

        return application

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

    @staticmethod
    def _duplicate_application_error(
        *,
        organization_id: UUID,
        job_id: UUID,
        candidate_id: UUID,
    ) -> ConflictError:
        return ConflictError(
            code="APPLICATION_ALREADY_EXISTS",
            message=(
                "Application already exists "
                "for this job and candidate."
            ),
            details={
                "organization_id": str(
                    organization_id
                ),
                "job_id": str(
                    job_id
                ),
                "candidate_id": str(
                    candidate_id
                ),
            },
        )

    @staticmethod
    def _application_not_found_error(
        *,
        organization_id: UUID,
        application_id: UUID,
    ) -> NotFoundError:
        return NotFoundError(
            code="APPLICATION_NOT_FOUND",
            message="Application was not found.",
            details={
                "organization_id": str(
                    organization_id
                ),
                "application_id": str(
                    application_id
                ),
            },
        )
