from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.api.routes.candidate_documents import get_candidate_document_service
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.document_chunk import (
    ChunkingRequest,
    ChunkSetPage,
    ChunkSetRead,
    DocumentChunkPage,
    DocumentChunkRead,
)
from app.services.candidate_document import CandidateDocumentService
from app.services.document_chunk import DocumentChunkService

router = APIRouter(
    prefix="/organizations/{organization_id}/candidates/{candidate_id}/documents/{document_id}/chunks",
    tags=["document chunks"],
)


def get_document_chunk_service(
    session: AsyncSession = Depends(get_db_session),
    documents: CandidateDocumentService = Depends(get_candidate_document_service),
) -> DocumentChunkService:
    return DocumentChunkService(session, documents, get_settings())


@router.post(
    "",
    response_model=ChunkSetRead,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": ChunkSetRead}},
)
async def build_chunks(
    organization_id: UUID,
    candidate_id: UUID,
    document_id: UUID,
    data: ChunkingRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    service: DocumentChunkService = Depends(get_document_chunk_service),
) -> ChunkSetRead:
    response.headers["Cache-Control"] = "private, no-store"
    chunk_set, created = await service.build_for_user(
        document_id,
        organization_id=organization_id,
        candidate_id=candidate_id,
        user_id=current_user.id,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return ChunkSetRead.model_validate(chunk_set)


@router.get("", response_model=ChunkSetPage)
async def list_chunk_sets(
    organization_id: UUID,
    candidate_id: UUID,
    document_id: UUID,
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    service: DocumentChunkService = Depends(get_document_chunk_service),
) -> ChunkSetPage:
    response.headers["Cache-Control"] = "private, no-store"
    chunk_sets, total = await service.list_for_user(
        document_id,
        organization_id=organization_id,
        candidate_id=candidate_id,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return ChunkSetPage(
        items=[ChunkSetRead.model_validate(item) for item in chunk_sets],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{chunk_set_id}", response_model=ChunkSetRead)
async def get_chunk_set(
    organization_id: UUID,
    candidate_id: UUID,
    document_id: UUID,
    chunk_set_id: UUID,
    response: Response,
    current_user: User = Depends(get_current_user),
    service: DocumentChunkService = Depends(get_document_chunk_service),
) -> ChunkSetRead:
    response.headers["Cache-Control"] = "private, no-store"
    chunk_set = await service.get_for_user(
        document_id,
        chunk_set_id,
        organization_id=organization_id,
        candidate_id=candidate_id,
        user_id=current_user.id,
    )
    return ChunkSetRead.model_validate(chunk_set)


@router.get("/{chunk_set_id}/items", response_model=DocumentChunkPage)
async def list_chunks(
    organization_id: UUID,
    candidate_id: UUID,
    document_id: UUID,
    chunk_set_id: UUID,
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    service: DocumentChunkService = Depends(get_document_chunk_service),
) -> DocumentChunkPage:
    response.headers["Cache-Control"] = "private, no-store"
    chunk_set, chunks = await service.chunks_for_user(
        document_id,
        chunk_set_id,
        organization_id=organization_id,
        candidate_id=candidate_id,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return DocumentChunkPage(
        chunk_set=ChunkSetRead.model_validate(chunk_set),
        items=[DocumentChunkRead.model_validate(item) for item in chunks],
        total=chunk_set.chunk_count,
        limit=limit,
        offset=offset,
    )
