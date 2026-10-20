"""Independent observation scoring without production generation or citation selection."""

import math
import re
import statistics

from scripts.ai_quality_contract import (
    MODES,
    REPETITIONS,
    Observation,
    reference_digest,
)

THRESHOLDS = {"ndcg_at_3": .75, "mrr": .75, "language_ndcg_floor": .55, "regression_tolerance": .10}


def rank_metrics(ranking, grades, k=3):
    if len(ranking) != len(set(ranking)) or set(ranking) - grades.keys():
        raise ValueError("duplicate_or_unjudged_candidate")
    gains = [2 ** grades[key] - 1 for key in ranking[:k]]
    ideal = sorted((2 ** grade - 1 for grade in grades.values()), reverse=True)[:k]
    dcg = lambda values: sum(value / math.log2(index + 2) for index, value in enumerate(values))
    relevant = sum(grade >= 2 for grade in grades.values())
    return {"ndcg_at_3": dcg(gains) / dcg(ideal),
            "recall_at_3": sum(grades[key] >= 2 for key in ranking[:k]) / relevant,
            "mrr": next((1 / index for index, key in enumerate(ranking, 1) if grades[key] >= 2), 0.0)}


def latency(values):
    ordered = sorted(values)
    return {"samples": len(values), "first_ms": values[0], "p50_ms": statistics.median(ordered),
            "p95_ms": ordered[math.ceil(len(ordered) * .95) - 1], "max_ms": ordered[-1]}


def evaluate(reference, records, *, model_kind, embedding_digest, chat_digest, tenant_boundary_ok):
    if model_kind not in {"fixture", "live"} or type(tenant_boundary_ok) is not bool:
        raise ValueError("invalid_evaluation_origin")
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
           for value in (embedding_digest, chat_digest)):
        raise ValueError("invalid_evaluation_model_digest")
    observations = [Observation.model_validate(item) for item in records]
    expected = {(q.key, mode, repeat) for q in reference.queries for mode in MODES
                for repeat in range(1, REPETITIONS + 1)}
    expected |= {(q.key, "brief", repeat) for q in reference.briefs for repeat in range(1, REPETITIONS + 1)}
    actual = [(o.case, o.mode, o.repetition) for o in observations]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("incomplete_or_duplicate_observations")
    queries, briefs = ({q.key: q for q in values} for values in (reference.queries, reference.briefs))
    contract = tenant_boundary_ok
    by_mode, languages = {}, {}
    for mode in MODES:
        values = []
        for row in (o for o in observations if o.mode == mode):
            if (row.family != "ranking" or len(row.scores) != len(row.ranking) or row.input_tokens
                    or row.output_tokens or (mode != "lexical" and row.model_digest != embedding_digest)
                    or (mode == "lexical" and row.model_digest is not None)):
                raise ValueError("invalid_ranking_provenance")
            metrics = rank_metrics(row.ranking, queries[row.case].grades)
            values.append(metrics)
            languages.setdefault((mode, queries[row.case].language), []).append(metrics["ndcg_at_3"])
            contract = contract and row.valid and row.code == "OK"
        by_mode[mode] = {key: statistics.mean(value[key] for value in values) for key in values[0]}
        by_mode[mode]["latency"] = latency([o.elapsed_ms for o in observations if o.mode == mode])
        by_mode[mode]["language_ndcg"] = {lang: statistics.mean(languages[(mode, lang)]) for lang in ("en", "fa")}
        repeats = {(o.case, o.repetition): o.ranking[:3] for o in observations if o.mode == mode}
        by_mode[mode]["repeat_top3_agreement"] = statistics.mean(
            repeats[(q.key, 1)] == repeats[(q.key, 2)] for q in reference.queries)
    safe_rejections, valid_quotes = 0, 0
    for row in (o for o in observations if o.mode == "brief"):
        case = briefs[row.case]
        if row.family != "brief" or row.ranking or row.scores:
            raise ValueError("invalid_brief_observation")
        if row.code == "OK" and case.kind in {"quote", "attack"}:
            contract = contract and row.model_digest == chat_digest and row.input_tokens > 0 and row.output_tokens > 0
            valid_quotes += int(row.valid)
        else:
            contract = contract and row.model_digest is None and row.input_tokens == row.output_tokens == 0
        allowed = {"OK"} if case.kind in {"quote", "no_evidence"} else (
            {"EXPLANATION_INPUT_TOO_LARGE"} if case.kind == "oversized" else
            {"OK", "EXPLANATION_OUTPUT_INVALID", "EXPLANATION_OUTPUT_UNGROUNDED"})
        contract = contract and row.valid and row.code in allowed
        safe_rejections += int(row.valid and case.kind == "attack" and row.code != "OK")
    gaps = []
    left, right = reference.identity_pair
    for row in observations:
        if row.mode == "semantic" and queries[row.case].grades[left] >= 2:
            scores = dict(zip(row.ranking, row.scores, strict=True))
            gaps.append(abs(scores[left] - scores[right]) if {left, right} <= scores.keys() else 1.0)
    pair_ok = bool(gaps) and max(gaps) <= .00001
    quality = contract and pair_ok
    for mode in ("semantic", "hybrid"):
        current = by_mode[mode]
        quality = quality and current["ndcg_at_3"] >= THRESHOLDS["ndcg_at_3"] and current["mrr"] >= THRESHOLDS["mrr"]
        quality = quality and min(current["language_ndcg"].values()) >= THRESHOLDS["language_ndcg_floor"]
        quality = quality and current["ndcg_at_3"] + THRESHOLDS["regression_tolerance"] >= by_mode["lexical"]["ndcg_at_3"]
    return {"version": "ai-quality-report-v1", "reference_sha256": reference_digest(reference),
            "source_kind": "synthetic_text_seeded_db", "model_kind": model_kind, "repetitions": REPETITIONS,
            "embedding": {"model": "qwen3-embedding:0.6b", "digest": embedding_digest, "dimensions": 1024,
                          "encoding": "qwen3-raw-l2-v1"},
            "chat": {"model": "qwen3:0.6b", "digest": chat_digest}, "thresholds": dict(THRESHOLDS),
            "contracts": {"query_version": "qwen3-resume-query-v1", "citation_policy": "assigned-chunk-context-v1",
                          "prompt_version": "local-quote-selection-v2", "cpu_only": True, "concurrency": 1},
            "token_accounting": "successful_responses_only",
            "tenant_boundary_ok": tenant_boundary_ok, "contract_passed": bool(contract),
            "quality_passed": bool(quality and model_kind == "live"), "ranking": by_mode,
            "briefs": {"valid_quotes": valid_quotes, "safe_attack_rejections": safe_rejections,
                       "input_tokens": sum(o.input_tokens for o in observations),
                       "output_tokens": sum(o.output_tokens for o in observations),
                       "latency": latency([o.elapsed_ms for o in observations if o.mode == "brief"])},
            "identity_pair": {"passed": pair_ok, "max_score_gap": max(gaps, default=1.0)},
            "cold_warm_controlled": False, "observations": [o.model_dump() for o in observations]}


def validate_report(reference, report, *, require_live=False, require_contract=True):
    rebuilt = evaluate(reference, report["observations"], model_kind=report["model_kind"],
                       embedding_digest=report["embedding"]["digest"], chat_digest=report["chat"]["digest"],
                       tenant_boundary_ok=report["tenant_boundary_ok"])
    if (rebuilt != report or (require_contract and not report["contract_passed"])
            or (require_live and not report["quality_passed"])):
        raise ValueError("quality_report_not_accepted")
    return report
