import asyncio
import json

import pytest

from app.core.grounded_explanations import ExplanationFailure
from app.core.local_chat import ChatResult
from app.core.semantic_embeddings import EmbeddingFailure, ModelIdentity
from scripts import model_benchmark as cli


class Encoder:
    async def identity(self):
        return ModelIdentity("a" * 64)

    async def encode(self, texts, identity):
        return ((1.0,) + (0.0,) * 1023,)


class Generator:
    async def generate(self, messages, schema):
        data = json.loads(messages[1]["content"])
        return ChatResult({"quotes": [{"criterion": item["key"], "source": item["source"], "quote": item["q"]}
                                     for item in data["criteria"]]}, "b" * 64, 100, 30)


def test_live_transport_report_contains_aggregate_timings_and_no_prompt_or_quotes():
    result = asyncio.run(cli.measure("http://ollama:11434", encoder=Encoder(), generator=Generator()))
    assert result["models_checked"] and result["chat"]["grounding_checked"]
    assert result["embedding"]["latency"]["samples"] == 3
    assert result["chat"]["latency"]["samples"] == 3 and result["chat"]["output_tokens"] == 90
    assert not result["cold_warm_controlled"] and result["source_kind"] == "synthetic_client_live_transport"
    assert "Python" not in json.dumps(result) and '"quotes"' not in json.dumps(result)


def test_ungrounded_model_output_fails_the_measurement():
    class Bad(Generator):
        async def generate(self, *args):
            return ChatResult({"quotes": [{"criterion": "skill", "source": "s0", "quote": "invented qualification"}]}, "b" * 64, 100, 30)
    with pytest.raises(ExplanationFailure):
        asyncio.run(cli.measure("http://ollama:11434", samples=1, encoder=Encoder(), generator=Bad()))


def test_wrong_vector_dimensions_fail_the_measurement():
    class Bad(Encoder):
        async def encode(self, *args): return ((1.0,),)
    with pytest.raises(EmbeddingFailure):
        asyncio.run(cli.measure("http://ollama:11434", samples=1, encoder=Bad(), generator=Generator()))


def test_plan_does_not_infer_or_load_a_model(monkeypatch, capsys):
    monkeypatch.setattr(cli, "measure", lambda *a, **k: pytest.fail("inference attempted"))
    assert cli.main([]) == 0
    assert json.loads(capsys.readouterr().out)["models_checked"] is False
