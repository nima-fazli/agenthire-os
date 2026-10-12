from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.job_retrieval import (
    JobCandidatePage,
    JobCandidateQuery,
    JobSearchProfileRead,
    JobSearchProfileWrite,
)
from app.services.job_retrieval import JobRetrievalService

router = APIRouter(
    prefix="/organizations/{organization_id}/jobs/{job_id}",
    tags=["job candidate retrieval"],
)


def get_job_retrieval_service(session: AsyncSession = Depends(get_db_session)):
    return JobRetrievalService(session, get_settings())


@router.put("/search-profile", response_model=JobSearchProfileRead)
async def put_profile(
    organization_id: UUID,
    job_id: UUID,
    data: JobSearchProfileWrite,
    response: Response,
    current_user: User = Depends(get_current_user),
    service: JobRetrievalService = Depends(get_job_retrieval_service),
) -> JobSearchProfileRead:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.put_profile(
        data, job_id=job_id, organization_id=organization_id, user_id=current_user.id
    )


@router.get("/search-profile", response_model=JobSearchProfileRead)
async def get_profile(
    organization_id: UUID,
    job_id: UUID,
    response: Response,
    current_user: User = Depends(get_current_user),
    service: JobRetrievalService = Depends(get_job_retrieval_service),
) -> JobSearchProfileRead:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.get_profile(
        job_id=job_id, organization_id=organization_id, user_id=current_user.id
    )


@router.get("/candidate-retrieval", response_model=JobCandidatePage)
async def retrieve_candidates(
    organization_id: UUID,
    job_id: UUID,
    data: Annotated[JobCandidateQuery, Query()],
    response: Response,
    current_user: User = Depends(get_current_user),
    service: JobRetrievalService = Depends(get_job_retrieval_service),
) -> JobCandidatePage:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.retrieve(
        data, job_id=job_id, organization_id=organization_id, user_id=current_user.id
    )
