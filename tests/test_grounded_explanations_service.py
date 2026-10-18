import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.core.grounded_explanations import ExplanationFailure
from app.core.local_chat import ChatResult
from app.schemas.grounded_explanations import ExplanationRequest
from app.services.grounded_explanations import GroundedExplanationService
from scripts.grounded_explanations_evaluation import example_snapshot, load_reference


@pytest.fixture
def context():
    session = AsyncMock(spec=AsyncSession)
    generator = AsyncMock()
    generator.generate.return_value = ChatResult({"quotes": [{"criterion": "skill", "source": "s0", "quote": "Python"}]}, "a" * 64, 100, 30)
    service = GroundedExplanationService(session, Settings(_env_file=None, explanations_enabled=True), generator)
    service._matching = AsyncMock()
    service._matching.evidence.return_value = example_snapshot()
    service._repository = AsyncMock()
    service._repository.check.return_value = {"authorized": True, "job_exists": True, "candidate_exists": True,
        "profile_current": True, "sources_current": True, "quotes_match": True, "validated_at": datetime.now(UTC)}
    return SimpleNamespace(service=service, session=session, generator=generator,
        scope={"organization_id": uuid4(), "user_id": uuid4(), "job_id": uuid4(), "candidate_id": uuid4()})


@pytest.mark.parametrize("language", ["fa", "en"])
def test_source_snapshot_closes_before_generation_and_output_is_deterministically_grounded(context, language):
    c = context

    async def generate(*args):
        assert c.session.rollback.await_count == 1
        return c.generator.generate.return_value

    c.generator.generate.side_effect = generate
    result = asyncio.run(c.service.explain(ExplanationRequest(language=language), **c.scope))
    assert result.language == language and result.model_digest == "a" * 64
    assert result.criteria[0].citation.quote == example_snapshot().criteria[0].evidence.text
    assert result.criteria[1].citation is None
    assert c.service._matching.evidence.await_count == 2 and c.service._repository.check.await_count == 2
    assert c.session.rollback.await_count == 2
    c.session.commit.assert_not_awaited()


def test_absent_evidence_does_not_contact_model_and_returns_explicit_missing_states(context):
    c = context
    c.service._matching.evidence.return_value = example_snapshot(load_reference()["cases"][-1])
    page = asyncio.run(c.service.explain(ExplanationRequest(), **c.scope))
    assert not page.generator_used and page.model_digest is None and page.input_tokens == page.output_tokens == 0
    assert all(item.state == "no_evidence" for item in page.criteria)
    c.generator.generate.assert_not_awaited()


@pytest.mark.parametrize("issue,code", [
    ("disabled", "EXPLANATIONS_DISABLED"), ("nonmember", "ORGANIZATION_NOT_FOUND"),
    ("changed", "EXPLANATION_SNAPSHOT_CHANGED"), ("revoked", "ORGANIZATION_NOT_FOUND"),
    ("stale", "EXPLANATION_SNAPSHOT_CHANGED"), ("quote_terms", "EXPLANATION_OUTPUT_UNGROUNDED"),
    ("fabrication", "EXPLANATION_OUTPUT_UNGROUNDED"), ("model", "EXPLANATION_MODEL_CHANGED"),
    ("timeout", "EXPLANATION_PROVIDER_TIMEOUT"), ("db", "EXPLANATION_DATABASE_UNAVAILABLE"),
    ("db_timeout", "EXPLANATION_DATABASE_TIMEOUT"),
])
def test_failures_discard_output_without_leaking_private_context_or_leaving_transactions(context, issue, code):
    c = context
    if issue == "disabled": c.service._settings.explanations_enabled = False
    elif issue == "nonmember": c.service._matching.evidence.side_effect = NotFoundError(code=code, message="Hidden.")
    elif issue == "changed":
        original = example_snapshot()
        c.service._matching.evidence.side_effect = [original, original.model_copy(update={"profile_revision": 2})]
    elif issue in {"revoked", "stale", "quote_terms"}:
        first = c.service._repository.check.return_value.copy()
        second = first | {{"revoked": "authorized", "stale": "sources_current", "quote_terms": "quotes_match"}[issue]: False}
        c.service._repository.check.side_effect = [first, second]
    elif issue == "fabrication":
        c.generator.generate.return_value = ChatResult({"quotes": [{"criterion": "skill", "source": "s0", "quote": "MIT degree"}]}, "a" * 64, 100, 30)
    elif issue == "model": c.generator.generate.side_effect = ExplanationFailure(code)
    elif issue == "timeout": c.generator.generate.side_effect = TimeoutError()
    else:
        c.service._repository.check.side_effect = DBAPIError("private resume", {"quote": "private resume"},
            SimpleNamespace(sqlstate="57014" if issue == "db_timeout" else "08006"), False)
    with pytest.raises(AppError) as caught:
        asyncio.run(c.service.explain(ExplanationRequest(), **c.scope))
    assert caught.value.code == code and "private resume" not in str(caught.value)
    assert c.session.rollback.await_count >= 1
    if issue in {"disabled", "nonmember", "db", "db_timeout"}:
        c.generator.generate.assert_not_awaited()


def test_cancellation_propagates_and_closes_the_read_session(context):
    context.generator.generate.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(context.service.explain(ExplanationRequest(), **context.scope))
    assert context.session.rollback.await_count == 2
