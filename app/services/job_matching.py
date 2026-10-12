from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.core.matching_evidence import summarize_evidence
from app.repositories.job_matching import JobMatchingRepository
from app.schemas.job_matching import (
    JobMatchEvidenceRead,
    JobMatchProfileRead,
    JobMatchProfileWrite,
)
from app.services.candidate import CandidateService
from app.services.job import JobService


class JobMatchingService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._jobs = JobService(session)
        self._candidates = CandidateService(session)
        self._repository = JobMatchingRepository(session)

    async def authorize(
        self,
        *,
        job_id: UUID,
        organization_id: UUID,
        user_id: UUID,
        candidate_id: UUID | None = None,
    ) -> None:
        await self._jobs.get_for_user(
            job_id, organization_id=organization_id, user_id=user_id
        )
        if candidate_id is not None:
            await self._candidates.get_for_user(
                candidate_id, organization_id=organization_id, user_id=user_id
            )

    @staticmethod
    def missing_profile() -> NotFoundError:
        return NotFoundError(
            code="JOB_MATCH_PROFILE_NOT_FOUND",
            message="Job match profile was not found.",
        )

    async def put_profile(
        self,
        data: JobMatchProfileWrite,
        *,
        job_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> JobMatchProfileRead:
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
            result = await self._repository.save_profile(
                current, **scope, criteria=[item.model_dump() for item in data.criteria]
            )
            if result is None:
                await self.authorize(**scope)
                raise self.missing_profile()
            profile = JobMatchProfileRead.model_validate(result)
            await self._session.commit()
            return profile
        except BaseException:
            await self._session.rollback()
            raise

    async def get_profile(
        self, *, job_id: UUID, organization_id: UUID, user_id: UUID
    ) -> JobMatchProfileRead:
        scope = {
            "job_id": job_id,
            "organization_id": organization_id,
            "user_id": user_id,
        }
        try:
            await self.authorize(**scope)
            result = await self._repository.get_profile(**scope)
            if result is None:
                await self.authorize(**scope)
                raise self.missing_profile()
            return JobMatchProfileRead.model_validate(result)
        except BaseException:
            await self._session.rollback()
            raise

    async def evidence(
        self, *, job_id: UUID, candidate_id: UUID, organization_id: UUID, user_id: UUID
    ) -> JobMatchEvidenceRead:
        scope = {
            "job_id": job_id,
            "candidate_id": candidate_id,
            "organization_id": organization_id,
            "user_id": user_id,
        }
        try:
            await self.authorize(**scope)
            result = await self._repository.evidence(
                **scope, timeout_ms=self._settings.document_search_timeout_ms
            )
            if result is None:
                await self.authorize(**scope)
                raise self.missing_profile()
            summary = summarize_evidence(
                (
                    (item["importance"], item["evidence"] is not None)
                    for item in result["criteria"]
                ),
                ready_documents=result["ready_documents"],
                indexed_documents=result["indexed_documents"],
            )
            return JobMatchEvidenceRead.model_validate(
                {
                    key: value
                    for key, value in result.items()
                    if key not in {"ready_documents", "indexed_documents"}
                }
                | {"summary": summary}
            )
        except DBAPIError as error:
            await self._session.rollback()
            if getattr(error.orig, "sqlstate", None) == "57014":
                raise AppError(
                    code="MATCH_EVIDENCE_TIMEOUT",
                    message="Match evidence exceeded its execution limit.",
                    status_code=503,
                ) from error
            raise
        except BaseException:
            await self._session.rollback()
            raise
