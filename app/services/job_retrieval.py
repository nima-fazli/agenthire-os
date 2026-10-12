from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.repositories.job_retrieval import JobRetrievalRepository
from app.schemas.job_retrieval import (
    JobCandidatePage,
    JobCandidateQuery,
    JobSearchProfileRead,
    JobSearchProfileWrite,
)
from app.services.job import JobService


class JobRetrievalService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._jobs = JobService(session)
        self._repository = JobRetrievalRepository(session)

    async def authorize(self, *, job_id: UUID, organization_id: UUID, user_id: UUID):
        return await self._jobs.get_for_user(
            job_id, organization_id=organization_id, user_id=user_id
        )

    @staticmethod
    def missing_profile() -> NotFoundError:
        return NotFoundError(
            code="JOB_SEARCH_PROFILE_NOT_FOUND",
            message="Job search profile was not found.",
        )

    async def put_profile(
        self,
        data: JobSearchProfileWrite,
        *,
        job_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> JobSearchProfileRead:
        scope = {
            "job_id": job_id,
            "organization_id": organization_id,
            "user_id": user_id,
        }
        try:
            await self.authorize(**scope)
            if await self._repository.lock_job(**scope) is None:
                await self.authorize(**scope)
                raise NotFoundError(code="JOB_NOT_FOUND", message="Job was not found.")
            current = await self._repository.get_profile(**scope)
            profile = await self._repository.save_profile(
                current, job_id=job_id, q=data.q, user_id=user_id
            )
            result = JobSearchProfileRead.model_validate(profile)
            await self._session.commit()
            return result
        except BaseException:
            await self._session.rollback()
            raise

    async def get_profile(
        self, *, job_id: UUID, organization_id: UUID, user_id: UUID
    ) -> JobSearchProfileRead:
        scope = {
            "job_id": job_id,
            "organization_id": organization_id,
            "user_id": user_id,
        }
        try:
            await self.authorize(**scope)
            profile = await self._repository.get_profile(**scope)
            if profile is None:
                await self.authorize(**scope)
                raise self.missing_profile()
            return JobSearchProfileRead.model_validate(profile)
        except BaseException:
            await self._session.rollback()
            raise

    async def retrieve(
        self,
        data: JobCandidateQuery,
        *,
        job_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> JobCandidatePage:
        scope = {
            "job_id": job_id,
            "organization_id": organization_id,
            "user_id": user_id,
        }
        try:
            await self.authorize(**scope)
            result = await self._repository.retrieve(
                **scope, data=data, timeout_ms=self._settings.document_search_timeout_ms
            )
            if result is None:
                await self.authorize(**scope)
                raise self.missing_profile()
            return JobCandidatePage(
                **result,
                job_id=job_id,
                applicants_only=data.applicants_only,
                limit=data.limit,
                offset=data.offset,
            )
        except DBAPIError as error:
            await self._session.rollback()
            if getattr(error.orig, "sqlstate", None) == "57014":
                raise AppError(
                    code="CANDIDATE_RETRIEVAL_TIMEOUT",
                    message="Candidate retrieval exceeded its execution limit.",
                    status_code=503,
                ) from error
            raise
        except BaseException:
            await self._session.rollback()
            raise
