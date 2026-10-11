from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application


class ApplicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, organization_id: UUID, job_id: UUID, candidate_id: UUID
    ) -> Application:
        application = Application(
            organization_id=organization_id, job_id=job_id, candidate_id=candidate_id
        )

        self._session.add(application)

        await self._session.flush()
        await self._session.refresh(application)

        return application

    async def get_by_job_and_candidate(
        self, *, organization_id: UUID, job_id: UUID, candidate_id: UUID
    ) -> Application | None:
        statement = select(Application).where(
            Application.organization_id == organization_id,
            Application.job_id == job_id,
            Application.candidate_id == candidate_id,
        )

        result = await self._session.execute(statement)

        return result.scalar_one_or_none()

    async def list_for_organization(self, organization_id: UUID) -> list[Application]:
        statement = (
            select(Application)
            .where(Application.organization_id == organization_id)
            .order_by(Application.created_at, Application.id)
        )

        result = await self._session.execute(statement)

        return list(result.scalars().all())

    async def get_for_organization(
        self, *, application_id: UUID, organization_id: UUID, for_update: bool = False
    ) -> Application | None:
        statement = select(Application).where(
            Application.id == application_id, Application.organization_id == organization_id
        )

        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)

        result = await self._session.execute(statement)

        return result.scalar_one_or_none()

    async def update_status(self, application: Application, *, status: str) -> Application:
        application.status = status

        await self._session.flush()
        await self._session.refresh(application)

        return application
