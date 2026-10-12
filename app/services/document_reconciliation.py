import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.document_reconciliation import (
    DEFAULT_AGE_SECONDS,
    MAX_KEYS,
    MIN_AGE_SECONDS,
    ReconciliationError,
    ReconciliationStorage,
    validate_key,
)
from app.repositories.document_reconciliation import DocumentReconciliationRepository


@dataclass(frozen=True)
class ReconciliationOutcome:
    key: str
    action: str


class DocumentReconciliationService:
    def __init__(self, session: AsyncSession, storage: ReconciliationStorage) -> None:
        self._session = session
        self._storage = storage
        self._repository = DocumentReconciliationRepository(session)

    async def run(
        self,
        *,
        keys: tuple[str, ...] = (),
        apply: bool = False,
        min_age_seconds: int = DEFAULT_AGE_SECONDS,
        emit: Callable[[ReconciliationOutcome], None] | None = None,
    ) -> tuple[ReconciliationOutcome, ...]:
        if (
            type(min_age_seconds) is not int
            or not MIN_AGE_SECONDS <= min_age_seconds <= 365 * MIN_AGE_SECONDS
        ):
            raise ReconciliationError("Minimum age must be between 1 and 365 days.")
        if len(keys) > MAX_KEYS or len(set(keys)) != len(keys) or (apply and not keys):
            raise ReconciliationError("Apply requires 1 to 200 distinct exact keys.")
        for key in keys:
            validate_key(key)
        if self._session.in_transaction():
            raise ReconciliationError(
                "Reconciliation requires a fresh database session."
            )
        selected = keys or self._storage.keys()
        outcomes = []
        try:
            async with asyncio.timeout(30):
                await self._repository.guard()
                referenced = (
                    await self._repository.referenced_keys(selected)
                    if selected
                    else set()
                )
                cutoff = time.time_ns() - min_age_seconds * 1_000_000_000
                for key in selected:
                    state = self._storage.inspect(key)
                    if key in referenced:
                        action = (
                            "referenced_missing" if state is None else "keep_referenced"
                        )
                    elif state is None:
                        action = "missing"
                    elif not state.safe:
                        action = "keep_unsafe"
                    elif state.modified_ns > cutoff:
                        action = "keep_young"
                    elif not apply:
                        action = "would_delete"
                    elif key in await self._repository.referenced_keys((key,)):
                        action = "keep_referenced"
                    else:
                        try:
                            removed = self._storage.remove_if_unchanged(key, state)
                            action = "deleted" if removed else "changed"
                        except ReconciliationError:
                            action = "delete_failed"
                    outcome = ReconciliationOutcome(key, action)
                    outcomes.append(outcome)
                    if emit is not None:
                        emit(outcome)
        except (SQLAlchemyError, TimeoutError) as error:
            raise ReconciliationError(
                "Database guard/reference check failed; earlier deleted objects remain deleted."
            ) from error
        finally:
            await self._session.rollback()
        return tuple(outcomes)
