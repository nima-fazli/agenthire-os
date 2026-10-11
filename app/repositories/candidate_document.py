from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_document import CandidateDocument


class CandidateDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        uploaded_by_user_id: UUID,
        filename: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
        storage_key: str,
        status: str,
    ) -> CandidateDocument:
        document = CandidateDocument(
            organization_id=organization_id,
            candidate_id=candidate_id,
            uploaded_by_user_id=uploaded_by_user_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            storage_key=storage_key,
            status=status,
        )
        self._session.add(document)
        await self._session.flush()
        await self._session.refresh(document)
        return document

    async def get_for_candidate(
        self,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        document_id: UUID,
        ready_only: bool = True,
        for_update: bool = False,
    ) -> CandidateDocument | None:
        statement = select(CandidateDocument).where(
            CandidateDocument.organization_id == organization_id,
            CandidateDocument.candidate_id == candidate_id,
            CandidateDocument.id == document_id,
        )
        if ready_only:
            statement = statement.where(CandidateDocument.status == "ready")
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_digest(
        self,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        sha256: str,
    ) -> CandidateDocument | None:
        result = await self._session.execute(
            select(CandidateDocument).where(
                CandidateDocument.organization_id == organization_id,
                CandidateDocument.candidate_id == candidate_id,
                CandidateDocument.sha256 == sha256,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_candidate(
        self,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        limit: int,
        offset: int,
    ) -> list[CandidateDocument]:
        result = await self._session.execute(
            select(CandidateDocument)
            .where(
                CandidateDocument.organization_id == organization_id,
                CandidateDocument.candidate_id == candidate_id,
                CandidateDocument.status == "ready",
            )
            .order_by(CandidateDocument.created_at, CandidateDocument.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def mark_deleting(self, document: CandidateDocument) -> None:
        document.status = "deleting"
        await self._session.flush()

    async def delete_for_candidate(
        self,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        document_id: UUID,
    ) -> None:
        await self._session.execute(
            delete(CandidateDocument).where(
                CandidateDocument.organization_id == organization_id,
                CandidateDocument.candidate_id == candidate_id,
                CandidateDocument.id == document_id,
            )
        )
