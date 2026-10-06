from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.job import JobCreate, JobRead, JobUpdate
from app.services.job import JobService

router = APIRouter(
    prefix="/organizations/{organization_id}/jobs",
    tags=["jobs"],
)


def get_job_service(
    session: AsyncSession = Depends(
        get_db_session
    ),
) -> JobService:
    return JobService(
        session
    )


@router.post(
    "",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_job(
    organization_id: UUID,
    data: JobCreate,
    current_user: User = Depends(
        get_current_user
    ),
    service: JobService = Depends(
        get_job_service
    ),
) -> JobRead:
    job = await service.create(
        data,
        organization_id=organization_id,
        user_id=current_user.id,
    )

    return JobRead.model_validate(
        job
    )


@router.get(
    "",
    response_model=list[JobRead],
)
async def list_jobs(
    organization_id: UUID,
    current_user: User = Depends(
        get_current_user
    ),
    service: JobService = Depends(
        get_job_service
    ),
) -> list[JobRead]:
    jobs = await service.list_for_user(
        organization_id=organization_id,
        user_id=current_user.id,
    )

    return [
        JobRead.model_validate(
            job
        )
        for job in jobs
    ]


@router.get(
    "/{job_id}",
    response_model=JobRead,
)
async def get_job(
    organization_id: UUID,
    job_id: UUID,
    current_user: User = Depends(
        get_current_user
    ),
    service: JobService = Depends(
        get_job_service
    ),
) -> JobRead:
    job = await service.get_for_user(
        job_id,
        organization_id=organization_id,
        user_id=current_user.id,
    )

    return JobRead.model_validate(
        job
    )


@router.patch(
    "/{job_id}",
    response_model=JobRead,
)
async def update_job(
    organization_id: UUID,
    job_id: UUID,
    data: JobUpdate,
    current_user: User = Depends(
        get_current_user
    ),
    service: JobService = Depends(
        get_job_service
    ),
) -> JobRead:
    job = await service.update_for_user(
        job_id,
        data,
        organization_id=organization_id,
        user_id=current_user.id,
    )

    return JobRead.model_validate(
        job
    )
