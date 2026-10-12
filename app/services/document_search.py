from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.repositories.document_search import DocumentSearchRepository
from app.repositories.organization_membership import OrganizationMembershipRepository
from app.schemas.document_search import (
    DocumentSearchHit,
    DocumentSearchPage,
    DocumentSearchQuery,
)


class DocumentSearchService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._memberships = OrganizationMembershipRepository(session)
        self._repository = DocumentSearchRepository(session)

    async def search_for_user(
        self,
        data: DocumentSearchQuery,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> DocumentSearchPage:
        membership = await self._memberships.get_by_user_and_organization(
            organization_id=organization_id,
            user_id=user_id,
        )
        if membership is None:
            raise NotFoundError(
                code="ORGANIZATION_NOT_FOUND", message="Organization was not found."
            )
        try:
            hits, total = await self._repository.search(
                organization_id=organization_id,
                user_id=user_id,
                data=data,
                timeout_ms=self._settings.document_search_timeout_ms,
            )
            return DocumentSearchPage(
                items=[DocumentSearchHit.model_validate(hit) for hit in hits],
                total=total,
                limit=data.limit,
                offset=data.offset,
            )
        except DBAPIError as error:
            await self._session.rollback()
            if getattr(error.orig, "sqlstate", None) == "57014":
                raise AppError(
                    code="DOCUMENT_SEARCH_TIMEOUT",
                    message="Search exceeded its execution limit. Use a more specific query.",
                    status_code=503,
                ) from error
            raise
        except BaseException:
            await self._session.rollback()
            raise
