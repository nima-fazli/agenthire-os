import copy
import math

import pytest

from scripts.ai_quality_contract import MODES, REPETITIONS, load_reference
from scripts.ai_quality_metrics import evaluate, latency, rank_metrics, validate_report


def perfect_records(reference=None):
    reference = reference or load_reference()
    records = []
    for repeat in range(1, REPETITIONS + 1):
        for query in reference.queries:
            ranking = sorted(query.grades, key=query.grades.get, reverse=True)
            for mode in MODES:
                records.append({"family": "ranking", "case": query.key, "mode": mode, "repetition": repeat,
                    "valid": True, "code": "OK", "ranking": ranking.copy(), "scores": [.5] * len(ranking),
                    "elapsed_ms": 10.0, "model_digest": None if mode == "lexical" else "f" * 64})
        for case in reference.briefs:
            generated = case.kind in {"quote", "attack"}
            records.append({"family": "brief", "case": case.key, "mode": "brief", "repetition": repeat,
                "valid": True, "code": "EXPLANATION_INPUT_TOO_LARGE" if case.kind == "oversized" else "OK",
                "elapsed_ms": 20.0, "model_digest": "e" * 64 if generated else None,
                "input_tokens": 100 if generated else 0, "output_tokens": 30 if generated else 0})
    return records


def report(records=None, *, kind="live"):
    return evaluate(load_reference(), perfect_records() if records is None else records,
                    model_kind=kind, embedding_digest="f" * 64, chat_digest="e" * 64, tenant_boundary_ok=True)


def test_metrics_match_hand_calculated_values():
    grades = {"a": 3, "b": 2, "c": 0}
    result = rank_metrics(["c", "b", "a"], grades)
    assert result["ndcg_at_3"] == pytest.approx((3 / math.log2(3) + 7 / 2) / (7 + 3 / math.log2(3)))
    assert result["recall_at_3"] == 1 and result["mrr"] == .5
    assert rank_metrics([], grades) == {"ndcg_at_3": 0, "recall_at_3": 0, "mrr": 0}
    with pytest.raises(ValueError):
        rank_metrics(["a", "a"], grades)


def test_fixture_can_pass_contract_but_never_real_quality():
    assert report(kind="fixture")["contract_passed"]
    assert not report(kind="fixture")["quality_passed"]
    validate_report(load_reference(), report(), require_live=True)
    with pytest.raises(ValueError):
        validate_report(load_reference(), report(kind="fixture"), require_live=True)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "nan", "digest", "family"])
def test_incomplete_or_untrusted_measurements_cannot_pass(mutation):
    rows = perfect_records()
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif mutation == "unknown":
        rows[0]["ranking"][0] = "unjudged"
    elif mutation == "nan":
        rows[0]["elapsed_ms"] = float("nan")
    elif mutation == "digest":
        rows[1]["model_digest"] = "0" * 64
    else:
        rows[0]["family"] = "brief"
    with pytest.raises(ValueError):
        report(rows)


def test_safe_attack_rejection_is_separate_from_valid_quote_yield():
    rows = perfect_records()
    attack = next(r for r in rows if r["case"] == "injected_en")
    attack.update(code="EXPLANATION_OUTPUT_UNGROUNDED", model_digest=None, input_tokens=0, output_tokens=0)
    result = report(rows)
    assert result["quality_passed"] and result["briefs"]["safe_attack_rejections"] == 1
    attack["code"] = "EXPLANATION_PROVIDER_TIMEOUT"
    assert not report(rows)["contract_passed"]


def test_no_evidence_cannot_claim_model_tokens_or_hide_failed_citations():
    rows = perfect_records()
    next(r for r in rows if r["case"] == "no_document")["input_tokens"] = 1
    assert not report(rows)["contract_passed"]
    rows = perfect_records()
    next(r for r in rows if r["case"] == "qualification")["valid"] = False
    assert not report(rows)["quality_passed"]


def test_actual_quality_thresholds_and_identity_counterfactual_are_enforced():
    rows = perfect_records()
    for row in rows:
        if row["mode"] in {"semantic", "hybrid"}:
            row["ranking"].remove("artist")
            row["ranking"].insert(0, "artist")
    assert not report(rows)["quality_passed"]
    rows = perfect_records()
    row = next(r for r in rows if r["case"] == "python_literal" and r["mode"] == "semantic")
    row["scores"][row["ranking"].index("backend_a")] = .6
    assert not report(rows)["identity_pair"]["passed"]


def test_report_flags_thresholds_and_aggregates_are_recomputed():
    for key in ("quality_passed", "contract_passed", "reference_sha256", "thresholds", "ranking"):
        data = copy.deepcopy(report())
        data[key] = False if isinstance(data[key], bool) else "tampered"
        with pytest.raises(ValueError):
            validate_report(load_reference(), data)


def test_small_sample_percentile_is_nearest_rank_and_first_is_observed_only():
    assert latency([90.0, 10.0, 50.0]) == {"samples": 3, "first_ms": 90, "p50_ms": 50, "p95_ms": 90, "max_ms": 90}
