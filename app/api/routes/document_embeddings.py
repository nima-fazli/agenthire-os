from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.api.routes.candidate_documents import get_candidate_document_service
from app.core.config import get_settings
from app.core.local_embeddings import LocalEmbeddingEncoder
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.document_embeddings import EmbeddingJobRead, EmbeddingRequest
from app.services.candidate_document import CandidateDocumentService
from app.services.document_embeddings import DocumentEmbeddingService

router = APIRouter(
    prefix="/organizations/{organization_id}/candidates/{candidate_id}/documents/{document_id}/embedding-jobs",
    tags=["local document embeddings"],
)


def get_document_embedding_service(
    session: AsyncSession = Depends(get_db_session),
    documents: CandidateDocumentService = Depends(get_candidate_document_service),
) -> DocumentEmbeddingService:
    settings = get_settings()
    encoder = LocalEmbeddingEncoder(settings.embedding_base_url, timeout_seconds=settings.embedding_timeout_seconds)
    return DocumentEmbeddingService(session, documents, encoder, settings)


@router.post("", response_model=EmbeddingJobRead, status_code=status.HTTP_202_ACCEPTED,
             responses={200: {"model": EmbeddingJobRead}})
async def request_embeddings(
    organization_id: UUID, candidate_id: UUID, document_id: UUID,
    data: EmbeddingRequest, response: Response,
    current_user: User = Depends(get_current_user),
    service: DocumentEmbeddingService = Depends(get_document_embedding_service),
) -> EmbeddingJobRead:
    response.headers["Cache-Control"] = "private, no-store"
    job, created = await service.request(document_id, data, organization_id=organization_id,
                                         candidate_id=candidate_id, user_id=current_user.id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return job


@router.get("/{job_id}", response_model=EmbeddingJobRead)
async def get_embedding_job(
    organization_id: UUID, candidate_id: UUID, document_id: UUID, job_id: UUID,
    response: Response,
    current_user: User = Depends(get_current_user),
    service: DocumentEmbeddingService = Depends(get_document_embedding_service),
) -> EmbeddingJobRead:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.get(document_id, job_id, organization_id=organization_id,
                              candidate_id=candidate_id, user_id=current_user.id)
