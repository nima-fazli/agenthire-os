from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.job_matching import (
    JobMatchEvidenceRead,
    JobMatchProfileRead,
    JobMatchProfileWrite,
    MatchEvidenceQuery,
)
from app.services.job_matching import JobMatchingService

router = APIRouter(
    prefix="/organizations/{organization_id}/jobs/{job_id}",
    tags=["job matching evidence"],
)


def get_job_matching_service(session: AsyncSession = Depends(get_db_session)):
    return JobMatchingService(session, get_settings())


@router.put("/match-profile", response_model=JobMatchProfileRead)
async def put_profile(
    organization_id: UUID,
    job_id: UUID,
    data: JobMatchProfileWrite,
    response: Response,
    current_user: User = Depends(get_current_user),
    service: JobMatchingService = Depends(get_job_matching_service),
) -> JobMatchProfileRead:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.put_profile(
        data, job_id=job_id, organization_id=organization_id, user_id=current_user.id
    )


@router.get("/match-profile", response_model=JobMatchProfileRead)
async def get_profile(
    organization_id: UUID,
    job_id: UUID,
    response: Response,
    current_user: User = Depends(get_current_user),
    service: JobMatchingService = Depends(get_job_matching_service),
) -> JobMatchProfileRead:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.get_profile(
        job_id=job_id, organization_id=organization_id, user_id=current_user.id
    )


@router.get(
    "/candidates/{candidate_id}/match-evidence", response_model=JobMatchEvidenceRead
)
async def match_evidence(
    organization_id: UUID,
    job_id: UUID,
    candidate_id: UUID,
    _query: Annotated[MatchEvidenceQuery, Query()],
    response: Response,
    current_user: User = Depends(get_current_user),
    service: JobMatchingService = Depends(get_job_matching_service),
) -> JobMatchEvidenceRead:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.evidence(
        job_id=job_id,
        candidate_id=candidate_id,
        organization_id=organization_id,
        user_id=current_user.id,
    )
