import asyncio
import time

from sqlalchemy.exc import DBAPIError

from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.grounded_explanations import (
    MODEL_TAG,
    ExplanationFailure,
    fingerprint,
    ground,
    prepare,
    render,
)
from app.repositories.grounded_explanations import GroundedExplanationRepository
from app.schemas.grounded_explanations import GroundedExplanation
from app.services.job_matching import JobMatchingService


class GroundedExplanationService:
    def __init__(self, session, settings, generator):
        self._session, self._settings, self._generator = session, settings, generator
        self._matching = JobMatchingService(session, settings)
        self._repository = GroundedExplanationRepository(session)

    async def checked(self, snapshot, citations, scope):
        result = await self._repository.check(snapshot, citations,
            timeout_ms=self._settings.document_search_timeout_ms,
            organization_id=scope["organization_id"], user_id=scope["user_id"])
        for field, code in (("authorized", "ORGANIZATION_NOT_FOUND"), ("job_exists", "JOB_NOT_FOUND"),
                            ("candidate_exists", "CANDIDATE_NOT_FOUND")):
            if not result[field]:
                raise NotFoundError(code=code, message="Requested resource was not found.")
        if not result["profile_current"] or not result["sources_current"]:
            raise ConflictError(code="EXPLANATION_SNAPSHOT_CHANGED", message="Evidence changed. Retry explanation.")
        if not result["quotes_match"]:
            raise ExplanationFailure("EXPLANATION_OUTPUT_UNGROUNDED")
        return result["validated_at"]

    async def explain(self, data, **scope):
        started = time.perf_counter()
        try:
            snapshot = await self._matching.evidence(**scope)
            if not self._settings.explanations_enabled:
                raise AppError(code="EXPLANATIONS_DISABLED", message="Local explanations are disabled.", status_code=503)
            await self.checked(snapshot, {}, scope)
            assignments, messages, schema = prepare(snapshot)
            pinned = fingerprint(snapshot)
            await self._session.rollback()
            generated = None
            if assignments:
                async with asyncio.timeout(self._settings.chat_timeout_seconds):
                    generated = await self._generator.generate(messages, schema)
            citations = ground(generated.payload, assignments) if generated else {}
            current = await self._matching.evidence(**scope)
            if fingerprint(current) != pinned:
                raise ConflictError(code="EXPLANATION_SNAPSHOT_CHANGED", message="Evidence changed. Retry explanation.")
            validated_at = await self.checked(current, citations, scope)
            return GroundedExplanation(
                job_id=current.job_id, candidate_id=current.candidate_id, candidate_name=current.candidate_name,
                profile_revision=current.profile_revision, profile_updated_at=current.profile_updated_at,
                observed_at=snapshot.observed_at, validated_at=validated_at, language=data.language,
                generator_used=generated is not None, model_tag=MODEL_TAG if generated else None,
                model_digest=generated.digest if generated else None,
                input_tokens=generated.input_tokens if generated else 0,
                output_tokens=generated.output_tokens if generated else 0,
                elapsed_ms=(time.perf_counter() - started) * 1000, summary=current.summary,
                **render(current, citations, data.language),
            )
        except ExplanationFailure as error:
            raise AppError(code=error.code, message="Local explanation could not be safely produced.",
                           status_code=422 if error.code == "EXPLANATION_INPUT_TOO_LARGE" else 503) from None
        except TimeoutError:
            raise AppError(code="EXPLANATION_PROVIDER_TIMEOUT", message="Local generation exceeded its execution limit.", status_code=503) from None
        except DBAPIError as error:
            code = "EXPLANATION_DATABASE_TIMEOUT" if getattr(error.orig, "sqlstate", None) == "57014" else "EXPLANATION_DATABASE_UNAVAILABLE"
            raise AppError(code=code, message="Explanation evidence could not be verified.", status_code=503) from None
        finally:
            await self._session.rollback()
