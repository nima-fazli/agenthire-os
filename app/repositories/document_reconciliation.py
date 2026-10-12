from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.document_reconciliation import MAX_KEYS, ReconciliationError, validate_key
from app.models.candidate_document import CandidateDocument


class DocumentReconciliationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def guard(self) -> None:
        # The caller supplies a fresh session. Reference reads after acquisition
        # must see commits from uploads that the guard waited for.
        await self._session.execute(
            text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        )
        await self._session.execute(text("SET LOCAL lock_timeout = '2000ms'"))
        await self._session.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        await self._session.execute(
            text("LOCK TABLE candidate_documents IN SHARE ROW EXCLUSIVE MODE")
        )

    async def referenced_keys(self, keys: tuple[str, ...]) -> set[str]:
        if not keys or len(keys) > MAX_KEYS:
            raise ReconciliationError("Reference checks require 1 to 200 exact keys.")
        for key in keys:
            validate_key(key)
        # Global across all organizations and both ready/deleting statuses.
        result = await self._session.execute(
            select(CandidateDocument.storage_key).where(
                CandidateDocument.storage_key.in_(keys)
            )
        )
        return set(result.scalars().all())
