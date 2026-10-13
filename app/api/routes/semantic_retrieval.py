from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.core.local_embeddings import LocalEmbeddingEncoder
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.semantic_retrieval import (
    SemanticDocumentQuery,
    SemanticJobQuery,
    SemanticPage,
)
from app.services.semantic_retrieval import SemanticRetrievalService

router = APIRouter(prefix="/organizations/{organization_id}", tags=["semantic retrieval"])


def get_semantic_retrieval_service(session: AsyncSession = Depends(get_db_session)):
    settings = get_settings()
    return SemanticRetrievalService(session, settings, LocalEmbeddingEncoder(
        settings.embedding_base_url, timeout_seconds=settings.embedding_timeout_seconds))


@router.post("/semantic-search", response_model=SemanticPage)
async def search_documents(organization_id: UUID, data: SemanticDocumentQuery, response: Response,
                           user: User = Depends(get_current_user),
                           service: SemanticRetrievalService = Depends(get_semantic_retrieval_service)):
    response.headers["Cache-Control"] = "private, no-store"
    return await service.search(data, organization_id=organization_id, user_id=user.id)


@router.post("/jobs/{job_id}/semantic-candidate-retrieval", response_model=SemanticPage)
async def retrieve_candidates(organization_id: UUID, job_id: UUID, data: SemanticJobQuery,
                              response: Response, user: User = Depends(get_current_user),
                              service: SemanticRetrievalService = Depends(get_semantic_retrieval_service)):
    response.headers["Cache-Control"] = "private, no-store"
    return await service.search(data, organization_id=organization_id, user_id=user.id, job_id=job_id)
