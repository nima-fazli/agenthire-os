from collections.abc import AsyncIterator
from typing import Annotated, BinaryIO
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from starlette.types import Receive, Scope, Send

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.core.document_storage import LocalDocumentStorage
from app.db.session import get_db_session
from app.models.candidate_document import CandidateDocument
from app.models.user import User
from app.schemas.candidate_document import CandidateDocumentRead, DocumentUpload
from app.services.candidate_document import CandidateDocumentService

router = APIRouter(
    prefix="/organizations/{organization_id}/candidates/{candidate_id}/documents",
    tags=["candidate documents"],
)


class DocumentContentResponse(StreamingResponse):
    def __init__(self, document: CandidateDocument, handle: BinaryIO) -> None:
        self._handle = handle
        super().__init__(
            self._stream(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.filename, safe='')}",
                "Content-Length": str(document.size_bytes),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def _stream(self) -> AsyncIterator[bytes]:
        while chunk := await run_in_threadpool(self._handle.read, 64 * 1024):
            yield chunk

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._handle.close()


def get_candidate_document_service(
    session: AsyncSession = Depends(get_db_session),
) -> CandidateDocumentService:
    settings = get_settings()
    return CandidateDocumentService(
        session,
        LocalDocumentStorage(settings.document_storage_path),
        max_bytes=settings.document_max_bytes,
        upload_timeout_seconds=settings.document_upload_timeout_seconds,
    )


@router.post(
    "",
    response_model=CandidateDocumentRead,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload_document(
    organization_id: UUID,
    candidate_id: UUID,
    request: Request,
    data: Annotated[DocumentUpload, Query()],
    current_user: User = Depends(get_current_user),
    service: CandidateDocumentService = Depends(get_candidate_document_service),
) -> CandidateDocumentRead:
    document = await service.upload(
        data,
        request.stream(),
        organization_id=organization_id,
        candidate_id=candidate_id,
        user_id=current_user.id,
        content_type=request.headers.get("content-type", ""),
        content_length=request.headers.get("content-length"),
    )
    return CandidateDocumentRead.model_validate(document)


@router.get("", response_model=list[CandidateDocumentRead])
async def list_documents(
    organization_id: UUID,
    candidate_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    service: CandidateDocumentService = Depends(get_candidate_document_service),
) -> list[CandidateDocumentRead]:
    documents = await service.list_for_user(
        organization_id=organization_id,
        candidate_id=candidate_id,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return [CandidateDocumentRead.model_validate(document) for document in documents]


@router.get("/{document_id}", response_model=CandidateDocumentRead)
async def get_document(
    organization_id: UUID,
    candidate_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    service: CandidateDocumentService = Depends(get_candidate_document_service),
) -> CandidateDocumentRead:
    document = await service.get_for_user(
        document_id,
        organization_id=organization_id,
        candidate_id=candidate_id,
        user_id=current_user.id,
    )
    return CandidateDocumentRead.model_validate(document)


@router.get("/{document_id}/content", response_class=StreamingResponse)
async def download_document(
    organization_id: UUID,
    candidate_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    service: CandidateDocumentService = Depends(get_candidate_document_service),
) -> StreamingResponse:
    document, handle = await service.download_for_user(
        document_id,
        organization_id=organization_id,
        candidate_id=candidate_id,
        user_id=current_user.id,
    )

    return DocumentContentResponse(document, handle)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    organization_id: UUID,
    candidate_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    service: CandidateDocumentService = Depends(get_candidate_document_service),
) -> Response:
    await service.delete_for_user(
        document_id,
        organization_id=organization_id,
        candidate_id=candidate_id,
        user_id=current_user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
