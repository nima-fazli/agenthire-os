import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.core.grounded_explanations import ground, prepare, render
from app.schemas.grounded_explanations import GroundedExplanation
from scripts.ai_quality_contract import load_reference
from scripts.ai_quality_fixture import FixtureGenerator
from scripts.ai_quality_smoke import brief_observation, rejected_observation
from scripts.grounded_explanations_evaluation import example_snapshot


def brief_fixture():
    reference = load_reference()
    case = reference.briefs[0]
    snapshot = example_snapshot({"text": case.context, "q": case.q})
    assignments, messages, schema = prepare(snapshot)
    generated = asyncio.run(FixtureGenerator(reference).generate(messages, schema))
    page = GroundedExplanation(**snapshot.model_dump(exclude={"criteria"}), **render(snapshot, ground(generated.payload, assignments), "en"),
        language="en", validated_at=snapshot.observed_at, generator_used=True, model_tag="qwen3:0.6b",
        model_digest=generated.digest, input_tokens=100, output_tokens=30, elapsed_ms=1)
    source = {"document_id": UUID(int=3), "chunk_set_id": UUID(int=4), "text": case.context,
              "parts": [case.context], "document_sha": "b" * 64}
    fixture = SimpleNamespace(brief_job=snapshot.job_id, candidates={case.key: snapshot.candidate_id}, witnesses={case.key: source})
    profile = SimpleNamespace(revision=1, updated_at=snapshot.profile_updated_at)
    return page.model_dump(mode="json"), case, fixture, profile


def test_independent_brief_check_rejects_validly_hashed_shortened_context():
    page, case, fixture, profile = brief_fixture()
    assert brief_observation(page, case, fixture, profile, "e" * 64)["valid"]
    changed = copy.deepcopy(page)
    changed["criteria"][0]["citation"]["quote"] = "Python"
    assert not brief_observation(changed, case, fixture, profile, "e" * 64)["valid"]
    changed = copy.deepcopy(page)
    changed["profile_revision"] += 1
    assert not brief_observation(changed, case, fixture, profile, "e" * 64)["valid"]


@pytest.mark.parametrize(("kind", "status", "code", "valid"), [
    ("attack", 503, "EXPLANATION_OUTPUT_INVALID", True),
    ("attack", 503, "EXPLANATION_OUTPUT_UNGROUNDED", True),
    ("attack", 503, "EXPLANATION_PROVIDER_TIMEOUT", False),
    ("quote", 503, "EXPLANATION_OUTPUT_INVALID", False),
    ("oversized", 422, "EXPLANATION_INPUT_TOO_LARGE", True),
    ("oversized", 503, "EXPLANATION_INPUT_TOO_LARGE", False),
    ("no_evidence", 401, "INVALID_ACCESS_TOKEN", False),
])
def test_only_predeclared_safe_rejections_are_success(kind, status, code, valid):
    assert rejected_observation(status, {"error": {"code": code}}, SimpleNamespace(kind=kind))["valid"] is valid


def test_collector_cleans_its_fixture_even_if_seeding_fails(monkeypatch):
    import scripts.ai_quality_smoke as module

    settings = SimpleNamespace(embedding_base_url="http://ollama:11434", chat_base_url="http://ollama:11434")
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(model_copy=lambda **_: settings))
    monkeypatch.setattr(module, "require_test_database", lambda *args: None)
    fixture = SimpleNamespace(seed=AsyncMock(side_effect=ValueError("synthetic")), cleanup=AsyncMock())
    monkeypatch.setattr(module, "QualityFixture", lambda _: fixture)
    disposed = AsyncMock()
    monkeypatch.setattr(module, "engine", SimpleNamespace(dispose=disposed))
    with pytest.raises(ValueError):
        asyncio.run(module.run())
    fixture.cleanup.assert_awaited_once()
    disposed.assert_awaited_once()
