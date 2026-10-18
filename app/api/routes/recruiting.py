from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.application import ApplicationStatus
from app.schemas.candidate import CandidateRead
from app.schemas.job import JobRead, JobStatus
from app.schemas.organization import OrganizationRead
from app.schemas.recruiting import (
    ApplicationItem,
    CandidateEdit,
    JobEdit,
    Page,
    PageOptions,
)
from app.services.recruiting import RecruitingService


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(tags=["recruiting workflow"], dependencies=[Depends(private_response)])


def page_options(q: str = Query(default="", max_length=120, pattern=r"^[^\x00]*$"),
                 limit: int = Query(default=20, ge=1, le=100),
                 offset: int = Query(default=0, ge=0, le=10_000)):
    return PageOptions(q=q, limit=limit, offset=offset)


Options = Annotated[PageOptions, Depends(page_options)]


def get_recruiting_service(session: AsyncSession = Depends(get_db_session)):
    return RecruitingService(session)


@router.get("/organizations/page", response_model=Page[OrganizationRead])
async def organizations_page(options: Options, user: User = Depends(get_current_user),
                             service=Depends(get_recruiting_service)):
    return await service.page("organizations", options, user_id=user.id)


@router.get("/organizations/{organization_id}/recruiting/jobs", response_model=Page[JobRead])
async def jobs_page(organization_id: UUID, options: Options, status: JobStatus | None = None,
                    user: User = Depends(get_current_user), service=Depends(get_recruiting_service)):
    return await service.page("jobs", options, user_id=user.id,
                              organization_id=organization_id, status=status)


@router.get("/organizations/{organization_id}/recruiting/candidates", response_model=Page[CandidateRead])
async def candidates_page(organization_id: UUID, options: Options,
                          user: User = Depends(get_current_user), service=Depends(get_recruiting_service)):
    return await service.page("candidates", options, user_id=user.id, organization_id=organization_id)


@router.get("/organizations/{organization_id}/recruiting/applications", response_model=Page[ApplicationItem])
async def applications_page(organization_id: UUID, options: Options,
                            status: ApplicationStatus | None = None, job_id: UUID | None = None,
                            candidate_id: UUID | None = None, user: User = Depends(get_current_user),
                            service=Depends(get_recruiting_service)):
    return await service.page("applications", options, user_id=user.id, organization_id=organization_id,
                              status=status, job_id=job_id, candidate_id=candidate_id)


@router.put("/organizations/{organization_id}/recruiting/jobs/{record_id}", response_model=JobRead)
async def edit_job(organization_id: UUID, record_id: UUID, data: JobEdit,
                   user: User = Depends(get_current_user), service=Depends(get_recruiting_service)):
    return await service.edit("jobs", record_id, data, organization_id=organization_id, user_id=user.id)


@router.put("/organizations/{organization_id}/recruiting/candidates/{record_id}", response_model=CandidateRead)
async def edit_candidate(organization_id: UUID, record_id: UUID, data: CandidateEdit,
                         user: User = Depends(get_current_user), service=Depends(get_recruiting_service)):
    return await service.edit("candidates", record_id, data, organization_id=organization_id, user_id=user.id)
