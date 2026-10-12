from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.document_search import DocumentSearchPage, DocumentSearchQuery
from app.services.document_search import DocumentSearchService

router = APIRouter(
    prefix="/organizations/{organization_id}/document-search",
    tags=["document search"],
)


def get_document_search_service(
    session: AsyncSession = Depends(get_db_session),
) -> DocumentSearchService:
    return DocumentSearchService(session, get_settings())


@router.get("", response_model=DocumentSearchPage)
async def search_documents(
    organization_id: UUID,
    data: Annotated[DocumentSearchQuery, Query()],
    response: Response,
    current_user: User = Depends(get_current_user),
    service: DocumentSearchService = Depends(get_document_search_service),
) -> DocumentSearchPage:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.search_for_user(
        data,
        organization_id=organization_id,
        user_id=current_user.id,
    )
