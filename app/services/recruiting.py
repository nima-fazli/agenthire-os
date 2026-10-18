from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import AppError, ConflictError, NotFoundError
from app.models.candidate import Candidate
from app.models.job import Job
from app.repositories.recruiting import RecruitingRepository
from app.schemas.application import ApplicationStatus
from app.services.application import allowed_application_statuses
from app.services.organization import OrganizationService


class RecruitingService:
    def __init__(self, session):
        self.session = session
        self.organizations = OrganizationService(session)
        self.repository = RecruitingRepository(session)

    async def page(self, kind, options, *, user_id, organization_id=None, **filters):
        try:
            await self.session.execute(text("SELECT set_config('statement_timeout', '2000', true)"))
            if kind != "organizations":
                await self.organizations.get_for_user(organization_id, user_id=user_id)
            result = await self.repository.page(
                kind, options, user_id=user_id, organization_id=organization_id, **filters)
            if kind == "applications":
                for item in result["items"]:
                    item["allowed_statuses"] = allowed_application_statuses(ApplicationStatus(item["status"]))
            return result
        except DBAPIError as error:
            await self.session.rollback()
            if getattr(error.orig, "sqlstate", None) == "57014":
                raise AppError(code="PAGE_QUERY_TIMEOUT", message="Search timed out.",
                               status_code=503) from error
            raise

    async def edit(self, kind, record_id, data, *, organization_id, user_id):
        await self.organizations.get_for_user(organization_id, user_id=user_id)
        model = Job if kind == "jobs" else Candidate
        try:
            result = await self.session.execute(
                select(model).where(model.id == record_id, model.organization_id == organization_id)
                .with_for_update(nowait=True).execution_options(populate_existing=True))
            record = result.scalar_one_or_none()
            if record is None:
                raise NotFoundError(code="JOB_NOT_FOUND" if kind == "jobs" else "CANDIDATE_NOT_FOUND",
                                    message="Record was not found.")
            if record.updated_at != data.expected_updated_at:
                raise ConflictError(code="RECORD_CHANGED",
                                    message="Record changed. Refresh it before editing.")
            for key, value in data.model_dump(exclude={"expected_updated_at"}).items():
                setattr(record, key, value)
            await self.session.flush()
            await self.session.refresh(record)
            await self.session.commit()
            return record
        except DBAPIError as error:
            await self.session.rollback()
            if getattr(error.orig, "sqlstate", None) == "55P03":
                raise AppError(code="RECORD_BUSY", message="A concurrent edit is still running.",
                               status_code=503) from error
            raise
        except Exception:
            await self.session.rollback()
            raise
