from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.core.local_chat import LocalChatGenerator
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.grounded_explanations import ExplanationRequest, GroundedExplanation
from app.services.grounded_explanations import GroundedExplanationService

router = APIRouter(prefix="/organizations/{organization_id}/jobs/{job_id}", tags=["grounded explanations"])


def get_explanation_service(session: AsyncSession = Depends(get_db_session)):
    settings = get_settings()
    return GroundedExplanationService(session, settings, LocalChatGenerator(
        settings.chat_base_url, timeout_seconds=settings.chat_timeout_seconds))


@router.post("/candidates/{candidate_id}/grounded-explanation", response_model=GroundedExplanation)
async def explain_candidate(organization_id: UUID, job_id: UUID, candidate_id: UUID,
                            data: ExplanationRequest, response: Response,
                            user: User = Depends(get_current_user),
                            service: GroundedExplanationService = Depends(get_explanation_service)):
    response.headers["Cache-Control"] = "private, no-store"
    return await service.explain(data, organization_id=organization_id, job_id=job_id,
                                 candidate_id=candidate_id, user_id=user.id)
