from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pdf_extraction import ExtractedPdf
from app.models.candidate_document import CandidateDocument
from app.models.document_extraction import DocumentExtraction


@dataclass(frozen=True)
class ExtractionTask:
    document_id: UUID
    storage_key: str
    size_bytes: int
    sha256: str
    lease_token: UUID


class DocumentExtractionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, document_id: UUID) -> DocumentExtraction:
        extraction = DocumentExtraction(
            document_id=document_id, status="queued", attempts=0
        )
        self._session.add(extraction)
        await self._session.flush()
        await self._session.refresh(extraction)
        return extraction

    async def get_for_candidate(
        self,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        document_id: UUID,
        for_update: bool = False,
    ) -> DocumentExtraction | None:
        statement = (
            select(DocumentExtraction)
            .join(CandidateDocument)
            .where(
                CandidateDocument.organization_id == organization_id,
                CandidateDocument.candidate_id == candidate_id,
                CandidateDocument.id == document_id,
                CandidateDocument.status == "ready",
            )
        )
        if for_update:
            statement = statement.with_for_update(
                of=DocumentExtraction
            ).execution_options(populate_existing=True)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def requeue(self, extraction: DocumentExtraction) -> DocumentExtraction:
        extraction.status = "queued"
        extraction.failure_code = None
        extraction.completed_at = None
        extraction.text = None
        extraction.page_count = None
        await self._session.flush()
        await self._session.refresh(extraction)
        return extraction

    async def claim_next(
        self, *, max_attempts: int, lease_seconds: int
    ) -> ExtractionTask | None:
        await self._session.execute(
            update(DocumentExtraction)
            .where(
                or_(
                    DocumentExtraction.status == "queued",
                    and_(
                        DocumentExtraction.status == "running",
                        DocumentExtraction.lease_expires_at <= func.clock_timestamp(),
                    ),
                ),
                DocumentExtraction.attempts >= max_attempts,
            )
            .values(
                status="failed",
                failure_code="EXTRACTION_RETRY_LIMIT",
                text=None,
                page_count=None,
                lease_token=None,
                lease_expires_at=None,
                completed_at=func.clock_timestamp(),
            )
        )
        result = await self._session.execute(
            select(DocumentExtraction, CandidateDocument, func.clock_timestamp())
            .join(CandidateDocument)
            .where(
                CandidateDocument.status == "ready",
                DocumentExtraction.attempts < max_attempts,
                or_(
                    DocumentExtraction.status == "queued",
                    and_(
                        DocumentExtraction.status == "running",
                        DocumentExtraction.lease_expires_at <= func.clock_timestamp(),
                    ),
                ),
            )
            .order_by(DocumentExtraction.created_at, DocumentExtraction.document_id)
            .limit(1)
            .with_for_update(skip_locked=True, of=DocumentExtraction)
            .execution_options(populate_existing=True)
        )
        row = result.one_or_none()
        if row is None:
            return None
        extraction, document, now = row
        token = uuid4()
        extraction.status = "running"
        extraction.attempts += 1
        extraction.lease_token = token
        extraction.lease_expires_at = now + timedelta(seconds=lease_seconds)
        await self._session.flush()
        return ExtractionTask(
            document.id,
            document.storage_key,
            document.size_bytes,
            document.sha256,
            token,
        )

    async def finish_if_owned(
        self,
        task: ExtractionTask,
        *,
        result: ExtractedPdf | None = None,
        failure_code: str | None = None,
    ) -> bool:
        if (result is None) == (failure_code is None):
            raise ValueError("Provide exactly one extraction result or failure code.")
        document_ready = exists(
            select(CandidateDocument.id).where(
                CandidateDocument.id == task.document_id,
                CandidateDocument.status == "ready",
                CandidateDocument.sha256 == task.sha256,
            )
        )
        outcome = await self._session.execute(
            update(DocumentExtraction)
            .where(
                DocumentExtraction.document_id == task.document_id,
                DocumentExtraction.status == "running",
                DocumentExtraction.lease_token == task.lease_token,
                DocumentExtraction.lease_expires_at > func.clock_timestamp(),
                document_ready,
            )
            .values(
                status="succeeded" if result is not None else "failed",
                lease_token=None,
                lease_expires_at=None,
                text=result.text if result else None,
                page_count=result.page_count if result else None,
                failure_code=failure_code,
                completed_at=func.clock_timestamp(),
            )
            .execution_options(synchronize_session=False)
        )
        return outcome.rowcount == 1
