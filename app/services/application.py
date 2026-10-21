from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models.application import Application
from app.repositories.application import ApplicationRepository
from app.repositories.candidate import CandidateRepository
from app.repositories.job import JobRepository
from app.repositories.organization_membership import OrganizationMembershipRepository
from app.schemas.application import (
    ApplicationCreate,
    ApplicationStatus,
    ApplicationStatusTransition,
)

_ALLOWED_STATUS_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.APPLIED: frozenset({ApplicationStatus.SCREENING, ApplicationStatus.REJECTED}),
    ApplicationStatus.SCREENING: frozenset(
        {ApplicationStatus.INTERVIEW, ApplicationStatus.REJECTED}
    ),
    ApplicationStatus.INTERVIEW: frozenset({ApplicationStatus.OFFER, ApplicationStatus.REJECTED}),
    ApplicationStatus.OFFER: frozenset({ApplicationStatus.HIRED, ApplicationStatus.REJECTED}),
    ApplicationStatus.HIRED: frozenset(),
    ApplicationStatus.REJECTED: frozenset(),
}


def allowed_application_statuses(status: ApplicationStatus) -> list[ApplicationStatus]:
    return sorted(_ALLOWED_STATUS_TRANSITIONS[status])


class ApplicationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = ApplicationRepository(session)
        self._job_repository = JobRepository(session)
        self._candidate_repository = CandidateRepository(session)
        self._membership_repository = OrganizationMembershipRepository(session)

    async def create(
        self, data: ApplicationCreate, *, organization_id: UUID, user_id: UUID
    ) -> Application:
        await self._require_membership(organization_id=organization_id, user_id=user_id)

        job = await self._job_repository.get_for_organization(
            job_id=data.job_id, organization_id=organization_id
        )

        if job is None:
            raise self._job_not_found_error(organization_id=organization_id, job_id=data.job_id)

        candidate = await self._candidate_repository.get_for_organization(
            candidate_id=data.candidate_id, organization_id=organization_id
        )

        if candidate is None:
            raise self._candidate_not_found_error(
                organization_id=organization_id, candidate_id=data.candidate_id
            )

        existing = await self._repository.get_by_job_and_candidate(
            organization_id=organization_id, job_id=data.job_id, candidate_id=data.candidate_id
        )

        if existing is not None:
            raise self._duplicate_application_error(
                organization_id=organization_id, job_id=data.job_id, candidate_id=data.candidate_id
            )

        try:
            application = await self._repository.create(
                organization_id=organization_id, job_id=data.job_id, candidate_id=data.candidate_id
            )

            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()

            existing = await self._repository.get_by_job_and_candidate(
                organization_id=organization_id, job_id=data.job_id, candidate_id=data.candidate_id
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

    async def transition_status_for_user(
        self,
        application_id: UUID,
        data: ApplicationStatusTransition,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> Application:
        await self._require_membership(organization_id=organization_id, user_id=user_id)

        try:
            application = await self._repository.get_for_organization(
                application_id=application_id, organization_id=organization_id, for_update=True
            )

            if application is None:
                raise self._application_not_found_error(
                    organization_id=organization_id, application_id=application_id
                )

            current_status = ApplicationStatus(application.status)
            requested_status = data.status

            if requested_status != current_status:
                allowed_statuses = _ALLOWED_STATUS_TRANSITIONS[current_status]
                if requested_status not in allowed_statuses:
                    raise ConflictError(
                        code="INVALID_APPLICATION_STATUS_TRANSITION",
                        message="Application status transition is not allowed.",
                        details={
                            "current_status": current_status.value,
                            "requested_status": requested_status.value,
                            "allowed_statuses": sorted(item.value for item in allowed_statuses),
                        },
                    )

                application = await self._repository.update_status(
                    application, status=requested_status.value
                )

            if requested_status != current_status:
                from app.core.config import get_settings
                settings = get_settings()
                if settings.agents_enabled:
                    from app.services.agent_workspace import queue_status_notice
                    await queue_status_notice(self._session, application, settings)

            # A same-state retry performs no update; commit releases the row lock.
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        return application

    async def list_for_user(self, *, organization_id: UUID, user_id: UUID) -> list[Application]:
        await self._require_membership(organization_id=organization_id, user_id=user_id)

        return await self._repository.list_for_organization(organization_id)

    async def get_for_user(
        self, application_id: UUID, *, organization_id: UUID, user_id: UUID
    ) -> Application:
        await self._require_membership(organization_id=organization_id, user_id=user_id)

        application = await self._repository.get_for_organization(
            application_id=application_id, organization_id=organization_id
        )

        if application is None:
            raise self._application_not_found_error(
                organization_id=organization_id, application_id=application_id
            )

        return application

    async def _require_membership(self, *, organization_id: UUID, user_id: UUID) -> None:
        membership = await self._membership_repository.get_by_user_and_organization(
            user_id=user_id, organization_id=organization_id
        )

        if membership is None:
            raise NotFoundError(
                code="ORGANIZATION_NOT_FOUND",
                message="Organization was not found.",
                details={"organization_id": str(organization_id)},
            )

    @staticmethod
    def _job_not_found_error(*, organization_id: UUID, job_id: UUID) -> NotFoundError:
        return NotFoundError(
            code="JOB_NOT_FOUND",
            message="Job was not found.",
            details={"organization_id": str(organization_id), "job_id": str(job_id)},
        )

    @staticmethod
    def _candidate_not_found_error(*, organization_id: UUID, candidate_id: UUID) -> NotFoundError:
        return NotFoundError(
            code="CANDIDATE_NOT_FOUND",
            message="Candidate was not found.",
            details={"organization_id": str(organization_id), "candidate_id": str(candidate_id)},
        )

    @staticmethod
    def _duplicate_application_error(
        *, organization_id: UUID, job_id: UUID, candidate_id: UUID
    ) -> ConflictError:
        return ConflictError(
            code="APPLICATION_ALREADY_EXISTS",
            message="Application already exists for this job and candidate.",
            details={
                "organization_id": str(organization_id),
                "job_id": str(job_id),
                "candidate_id": str(candidate_id),
            },
        )

    @staticmethod
    def _application_not_found_error(
        *, organization_id: UUID, application_id: UUID
    ) -> NotFoundError:
        return NotFoundError(
            code="APPLICATION_NOT_FOUND",
            message="Application was not found.",
            details={
                "organization_id": str(organization_id),
                "application_id": str(application_id),
            },
        )
