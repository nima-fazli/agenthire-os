"""Serial opt-in live CPU transport samples; fixed models and synthetic sources."""

import argparse
import asyncio
import json
import time

from app.core.benchmark_metrics import distribution
from app.core.grounded_explanations import ExplanationFailure, ground, prepare
from app.core.local_chat import LocalChatGenerator
from app.core.local_embeddings import LocalEmbeddingEncoder
from app.core.semantic_embeddings import DIMENSIONS, EmbeddingFailure, local_base_url
from scripts.grounded_explanations_evaluation import example_snapshot, load_reference


async def measure(base_url, *, samples=3, encoder=None, generator=None):
    base_url = local_base_url(base_url)
    if type(samples) is not int or not 1 <= samples <= 4:
        raise ValueError("Model samples must be 1..4.")
    encoder = encoder or LocalEmbeddingEncoder(base_url)
    generator = generator or LocalChatGenerator(base_url)
    identity = await encoder.identity()
    embedding, chat, input_tokens, output_tokens = [], [], [], []
    digest = None
    cases = [case for case in load_reference()["cases"] if case["text"] and case["key"] != "injected"]
    for index in range(samples):
        case = cases[index % len(cases)]
        started = time.monotonic()
        vectors = await encoder.encode((case["text"],), identity)
        if len(vectors) != 1 or len(vectors[0]) != DIMENSIONS:
            raise EmbeddingFailure("EMBEDDING_PROVIDER_RESPONSE_INVALID")
        embedding.append((time.monotonic() - started) * 1000)
    for index in range(samples):
        snapshot = example_snapshot(cases[index % len(cases)])
        assignments, messages, schema = prepare(snapshot)
        started = time.monotonic()
        result = await generator.generate(messages, schema)
        ground(result.payload, assignments)
        if digest is not None and result.digest != digest:
            raise ExplanationFailure("EXPLANATION_MODEL_CHANGED")
        digest = result.digest
        chat.append((time.monotonic() - started) * 1000)
        input_tokens.append(result.input_tokens)
        output_tokens.append(result.output_tokens)
    if await encoder.identity() != identity:
        raise EmbeddingFailure("EMBEDDING_MODEL_CHANGED")
    return {"version": "model-benchmark-v1", "status": "passed", "source_kind": "synthetic_client_live_transport",
            "models_checked": True, "concurrency": 1, "cpu_only": True, "cold_warm_controlled": False,
            "embedding": {"model": "qwen3-embedding:0.6b", "digest": identity.digest, "dimensions": DIMENSIONS,
                          "latency": distribution(embedding), "first_ms": round(embedding[0], 3)},
            "chat": {"model": "qwen3:0.6b", "digest": digest, "grounding_checked": True,
                     "latency": distribution(chat), "first_ms": round(chat[0], 3),
                     "input_tokens": sum(input_tokens), "output_tokens": sum(output_tokens)}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--base-url", default="http://ollama:11434")
    parser.add_argument("--samples", type=int, choices=range(1, 5), default=3)
    args = parser.parse_args(argv)
    try:
        local_base_url(args.base_url)
    except (ValueError, EmbeddingFailure):
        print(json.dumps({"status": "failed", "diagnostic": "invalid_model_origin", "models_checked": False}))
        return 2
    if not args.execute:
        print(json.dumps({"status": "plan", "samples_per_model": args.samples, "concurrency": 1,
                          "models_checked": False, "inference_requires": "--execute"}))
        return 0
    try:
        report, code = asyncio.run(measure(args.base_url, samples=args.samples)), 0
    except (EmbeddingFailure, ExplanationFailure) as error:
        report, code = {"status": "failed", "models_checked": True, "diagnostic": error.code}, 1
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError):
        report, code = {"status": "failed", "models_checked": True, "diagnostic": "model_benchmark_unavailable"}, 1
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
