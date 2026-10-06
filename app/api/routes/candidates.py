from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.candidate import CandidateCreate, CandidateRead
from app.services.candidate import CandidateService

router = APIRouter(
    prefix="/organizations/{organization_id}/candidates",
    tags=["candidates"],
)


def get_candidate_service(
    session: AsyncSession = Depends(
        get_db_session
    ),
) -> CandidateService:
    return CandidateService(
        session
    )


@router.post(
    "",
    response_model=CandidateRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_candidate(
    organization_id: UUID,
    data: CandidateCreate,
    current_user: User = Depends(
        get_current_user
    ),
    service: CandidateService = Depends(
        get_candidate_service
    ),
) -> CandidateRead:
    candidate = await service.create(
        data,
        organization_id=organization_id,
        user_id=current_user.id,
    )

    return CandidateRead.model_validate(
        candidate
    )


@router.get(
    "",
    response_model=list[CandidateRead],
)
async def list_candidates(
    organization_id: UUID,
    current_user: User = Depends(
        get_current_user
    ),
    service: CandidateService = Depends(
        get_candidate_service
    ),
) -> list[CandidateRead]:
    candidates = await service.list_for_user(
        organization_id=organization_id,
        user_id=current_user.id,
    )

    return [
        CandidateRead.model_validate(
            candidate
        )
        for candidate in candidates
    ]


@router.get(
    "/{candidate_id}",
    response_model=CandidateRead,
)
async def get_candidate(
    organization_id: UUID,
    candidate_id: UUID,
    current_user: User = Depends(
        get_current_user
    ),
    service: CandidateService = Depends(
        get_candidate_service
    ),
) -> CandidateRead:
    candidate = await service.get_for_user(
        candidate_id,
        organization_id=organization_id,
        user_id=current_user.id,
    )

    return CandidateRead.model_validate(
        candidate
    )
