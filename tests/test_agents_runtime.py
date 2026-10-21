import asyncio
import io
import json

import pytest

from app.core.agent_runtime import NoRedirect, OllamaAgentModel, ReplayModel, agent_turn
from app.core.agent_tools import AgentFailure
from app.core.config import Settings
from app.tools.demo_seed import CRITERIA, RESUMES
from scripts import agent_evaluation


def snapshot():
    return {
        "job_title": "Backend Engineer",
        "criteria": CRITERIA,
        "sources": [{"id": "synthetic:alex", "text": RESUMES[0][2]}],
    }


def provider(monkeypatch, mutate=None, changed=False):
    requests = []
    tags = 0

    class Opener:
        def open(self, request, timeout):
            nonlocal tags
            if request.full_url.endswith("/api/tags"):
                tags += 1
                return io.BytesIO(
                    json.dumps(
                        {
                            "models": [
                                {
                                    "name": "qwen3:4b",
                                    "digest": ("b" if changed and tags > 1 else "a")
                                    * 64,
                                }
                            ]
                        }
                    ).encode()
                )
            requests.append(json.loads(request.data))
            value = {
                "model": "qwen3:4b",
                "done": True,
                "done_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"name": "get_job", "arguments": {}}),
                },
                "prompt_eval_count": 100,
                "eval_count": 15,
            }
            if mutate:
                mutate(value)
            return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr("urllib.request.build_opener", lambda *_: Opener())
    return requests


def test_actual_provider_contract_uses_json_actions_and_checks_model_identity(
    monkeypatch,
):
    requests = provider(monkeypatch)
    state = asyncio.run(
        agent_turn(
            "recruiter",
            snapshot(),
            {},
            "Review this application",
            OllamaAgentModel(Settings(_env_file=None)),
        )
    )
    assert (
        state["event"]["tool"] == "get_job"
        and state["usage"] == [100, 15]
        and state["model_digest"] == "a" * 64
    )
    assert (
        "oneOf" in requests[0]["format"]
        and "tools" not in requests[0]
        and requests[0]["think"] is False
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda x: x.update(model="foreign"),
        lambda x: x.update(done_reason="length"),
        lambda x: x.update(message=[]),
        lambda x: x.update(eval_count=0),
        lambda x: x["message"].update(content="not JSON"),
        lambda x: x["message"].update(
            content='{"name":"get_job","arguments":{},"organization_id":"foreign"}'
        ),
    ],
)
def test_malformed_truncated_or_fabricated_provider_output_never_becomes_a_tool_action(
    monkeypatch, mutate
):
    provider(monkeypatch, mutate)
    with pytest.raises(AgentFailure):
        asyncio.run(
            agent_turn(
                "recruiter",
                snapshot(),
                {},
                "Review this application",
                OllamaAgentModel(Settings(_env_file=None)),
            )
        )


def test_model_change_during_inference_is_rejected(monkeypatch):
    provider(monkeypatch, changed=True)
    with pytest.raises(AgentFailure, match="MODEL_CHANGED"):
        asyncio.run(
            agent_turn(
                "recruiter",
                snapshot(),
                {},
                "Review this application",
                OllamaAgentModel(Settings(_env_file=None)),
            )
        )


def test_redirect_is_never_followed():
    response = io.BytesIO(b"")
    with pytest.raises(AgentFailure, match="MODEL_REDIRECT_BLOCKED"):
        NoRedirect().redirect_request(
            None, response, 302, "redirect", {}, "https://external.example"
        )
    assert response.closed


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"models": "wrong"},
        {"models": [42]},
        {"models": [{"name": "qwen3:4b", "digest": 123}]},
    ],
)
def test_malformed_model_catalog_has_an_explicit_failure(monkeypatch, value):
    class Opener:
        def open(self, *_args, **_kwargs):
            return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr("urllib.request.build_opener", lambda *_: Opener())
    with pytest.raises(AgentFailure):
        OllamaAgentModel(Settings(_env_file=None))._identity()


def test_old_runtime_checkpoints_are_rejected():
    with pytest.raises(AgentFailure, match="RUNTIME_VERSION_CHANGED"):
        asyncio.run(
            agent_turn(
                "recruiter",
                snapshot(),
                {"protocol": "unknown-v0"},
                "Review this application",
                ReplayModel(),
            )
        )


def test_hosted_tracing_stays_disabled_even_when_parent_environment_enables_it(
    monkeypatch,
):
    calls = []
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "synthetic-not-a-real-key")
    monkeypatch.setattr(
        "langsmith.Client.create_run", lambda *_args, **_kwargs: calls.append(True)
    )
    asyncio.run(
        agent_turn(
            "recruiter", snapshot(), {}, "Review this application", ReplayModel()
        )
    )
    assert calls == []


def test_replay_and_partial_evaluations_cannot_claim_full_live_quality():
    report = asyncio.run(
        agent_evaluation.evaluate(repeat=1, case_ids=["negation", "late_evidence"])
    )
    assert (
        report["contract_passed"]
        and not report["live_quality_accepted"]
        and not report["full_corpus"]
    )
    assert all(
        r["tool_trace"][-1]["tool"] == "submit_review" for r in report["observations"]
    )


def test_substituting_replay_for_live_cannot_earn_live_acceptance(monkeypatch):
    monkeypatch.setattr(agent_evaluation, "OllamaAgentModel", lambda _: ReplayModel())
    report = asyncio.run(agent_evaluation.evaluate(mode="live", repeat=1))
    assert all(r["completed"] for r in report["observations"])
    assert not report["contract_passed"] and not report["live_quality_accepted"]
