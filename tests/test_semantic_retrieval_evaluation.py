import copy

import pytest

from scripts.semantic_retrieval_evaluation import evaluate, load_reference


def observations(reference):
    return [{"case": case["key"], "mode": mode,
             "ranking": [] if mode == "lexical" else ["backend"], "elapsed_ms": 1.5}
            for case in reference["cases"] for mode in ("lexical", "semantic", "hybrid")]


def test_reference_comparison_records_versions_latency_and_separate_model_kind():
    reference = load_reference()
    report = evaluate(reference, observations(reference), model_digest="a" * 64, model_kind="fixture", source_kind="example")
    assert report["gate_passed"] and report["mean_ndcg_at_1"] == {"lexical": 0, "semantic": 1, "hybrid": 1}
    assert report["model_kind"] == "fixture" and report["dimensions"] == 1024
    assert report["source_kind"] == "example"
    assert "q" not in report["cases"][0] and "ranking" not in report["cases"][0]
    changed = copy.deepcopy(reference)
    changed["passages"]["backend"] += " changed"
    other = evaluate(changed, observations(changed), model_digest="a" * 64, model_kind="fixture", source_kind="example")
    assert other["reference_sha256"] != report["reference_sha256"]


@pytest.mark.parametrize("ranking", [["artist"], ["foreign"], []])
def test_relevance_or_tenant_regressions_fail_the_gate(ranking):
    reference = load_reference()
    data = observations(reference)
    data[1]["ranking"] = ranking
    report = evaluate(reference, data, model_digest="a" * 64, model_kind="live", source_kind="example")
    assert not report["gate_passed"] and report["failures"]


@pytest.mark.parametrize("change", ["missing", "duplicate", "nan", "negative"])
def test_incomplete_or_invalid_observations_are_input_errors(change):
    reference = load_reference()
    data = observations(reference)
    if change == "missing": data.pop()
    elif change == "duplicate": data.append(data[0])
    else: data[0]["elapsed_ms"] = float("nan") if change == "nan" else -1
    with pytest.raises(ValueError):
        evaluate(reference, data, model_digest="a" * 64, model_kind="fixture", source_kind="example")


@pytest.mark.parametrize("change", ["version", "digest", "source", "boolean-latency"])
def test_reference_and_provenance_cannot_be_mislabeled(change):
    reference = load_reference()
    data = observations(reference)
    digest, source = "a" * 64, "example"
    if change == "version": reference["version"] = "unknown"
    elif change == "digest": digest = "g" * 64
    elif change == "source": source = "unverified"
    else: data[0]["elapsed_ms"] = True
    with pytest.raises(ValueError):
        evaluate(reference, data, model_digest=digest, model_kind="fixture", source_kind=source)
