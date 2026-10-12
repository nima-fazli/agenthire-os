import hashlib
import json
from datetime import UTC, datetime

from app.core.retrieval_metrics import (
    confusion_counts,
    defined_mean,
    evidence_rates,
    ranking_metrics,
)
from app.schemas.retrieval_evaluation import (
    EvaluationObservations,
    EvaluationReport,
    EvaluationSuite,
)


class EvaluationDataError(ValueError):
    pass


def suite_digest(suite: EvaluationSuite) -> str:
    canonical = json.dumps(
        suite.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RetrievalEvaluationService:
    def evaluate(
        self, suite: EvaluationSuite, observations: EvaluationObservations
    ) -> EvaluationReport:
        digest = suite_digest(suite)
        if observations.suite_sha256 != digest:
            raise EvaluationDataError("SUITE_HASH_MISMATCH")
        ranking = {case.key: case for case in observations.ranking}
        evidence = {case.key: case for case in observations.evidence}
        if set(ranking) != {case.key for case in suite.ranking} or set(evidence) != {
            case.key for case in suite.evidence
        }:
            raise EvaluationDataError("CASE_SET_MISMATCH")
        ranked_results, evidence_results, failures = [], [], []

        def fail(scope, code, **details):
            failures.append({"scope": scope, "code": code, **details})

        for case in suite.ranking:
            observed = ranking[case.key].ranked_ids
            metrics = ranking_metrics(observed, case.judgments, k=case.k)
            invalid = ranking[case.key].provenance_failures
            ranked_results.append(
                {"key": case.key, **metrics, "provenance_failures": invalid}
            )
            if invalid:
                fail(case.key, "INVALID_PROVENANCE")
            if metrics["unjudged_count"]:
                fail(case.key, "UNJUDGED_RESULT")
            if set(observed).intersection(case.forbidden):
                fail(case.key, "FORBIDDEN_RESULT")
            if metrics["relevant_count"] == 0 and observed:
                fail(case.key, "EXPECTED_EMPTY")

        for case in suite.evidence:
            observed = evidence[case.key]
            if observed.profile_revision != case.profile_revision:
                raise EvaluationDataError("PROFILE_REVISION_MISMATCH")
            if {item.key for item in observed.criteria} != set(case.expected):
                raise EvaluationDataError("CRITERIA_SET_MISMATCH")
            counts = confusion_counts(
                case.expected, {item.key: item.found for item in observed.criteria}
            )
            invalid = sum(item.provenance_valid is False for item in observed.criteria)
            source_matches = observed.source_status == case.source_status
            evidence_results.append(
                {
                    "key": case.key,
                    **counts,
                    "provenance_failures": invalid,
                    "source_status_matches": source_matches,
                }
            )
            if invalid:
                fail(case.key, "INVALID_PROVENANCE")
            if not source_matches:
                fail(case.key, "SOURCE_STATUS_CHANGED")

        positive_queries = [row for row in ranked_results if row["relevant_count"]]
        aggregate = {
            "ranking_cases": len(positive_queries),
            "empty_ranking_cases": len(ranked_results) - len(positive_queries),
            **{
                "mean_" + metric: defined_mean(
                    [row[metric] for row in positive_queries]
                )
                for metric in (
                    "precision_at_k",
                    "recall_at_k",
                    "ndcg_at_k",
                    "reciprocal_rank_at_k",
                )
            },
            **evidence_rates(
                {
                    key: sum(row[key] for row in evidence_results)
                    for key in (
                        "true_positive",
                        "false_positive",
                        "false_negative",
                        "true_negative",
                    )
                }
            ),
        }
        for metric, minimum in suite.thresholds.model_dump().items():
            if minimum is None:
                continue
            actual = aggregate[metric]
            if actual is None:
                fail("overall", "UNDEFINED_METRIC", metric=metric, minimum=minimum)
            elif actual + 1e-12 < minimum:
                fail(
                    "overall",
                    "BELOW_THRESHOLD",
                    metric=metric,
                    actual=actual,
                    minimum=minimum,
                )
        return EvaluationReport.model_validate(
            {
                "suite_id": suite.suite_id,
                "suite_sha256": digest,
                "corpus_sha256": suite.corpus_sha256,
                "label_kind": suite.label_kind,
                "source_kind": observations.source_kind,
                "search_version": observations.search_version,
                "retrieval_version": observations.retrieval_version,
                "matching_version": observations.matching_version,
                "chunk_policies": observations.chunk_policies,
                "evaluated_at": datetime.now(UTC),
                "ranking": ranked_results,
                "evidence": evidence_results,
                "aggregate": aggregate,
                "failures": failures,
                "gate_passed": not failures,
            }
        )
