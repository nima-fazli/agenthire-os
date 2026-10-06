from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job


class JobRepository:
    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def create(
        self,
        *,
        organization_id: UUID,
        title: str,
        description: str,
        status: str,
    ) -> Job:
        job = Job(
            organization_id=organization_id,
            title=title,
            description=description,
            status=status,
        )

        self._session.add(job)

        await self._session.flush()
        await self._session.refresh(job)

        return job

    async def update(
        self,
        job: Job,
        *,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> Job:
        if title is not None:
            job.title = title

        if description is not None:
            job.description = description

        if status is not None:
            job.status = status

        await self._session.flush()
        await self._session.refresh(job)

        return job

    async def list_for_organization(
        self,
        organization_id: UUID,
    ) -> list[Job]:
        statement = (
            select(Job)
            .where(
                Job.organization_id
                == organization_id
            )
            .order_by(
                Job.created_at,
                Job.id,
            )
        )

        result = await self._session.execute(
            statement
        )

        return list(
            result.scalars().all()
        )

    async def get_for_organization(
        self,
        *,
        job_id: UUID,
        organization_id: UUID,
    ) -> Job | None:
        statement = select(Job).where(
            Job.id == job_id,
            Job.organization_id
            == organization_id,
        )

        result = await self._session.execute(
            statement
        )

        return result.scalar_one_or_none()
