import json

import pytest

from app.schemas.retrieval_evaluation import EvaluationObservations, EvaluationSuite
from app.services.retrieval_evaluation import (
    EvaluationDataError,
    RetrievalEvaluationService,
    suite_digest,
)
from scripts.evaluation_cases import load_example, load_suite


def evaluate(data=None, suite=None):
    return RetrievalEvaluationService().evaluate(
        suite or load_suite(),
        EvaluationObservations.model_validate(data)
        if data is not None
        else load_example(),
    )


def test_example_reports_measured_limits_and_defined_aggregation():
    report = evaluate()
    assert report.gate_passed and report.source_kind == "example"
    assert (
        report.aggregate.ranking_cases == 4
        and report.aggregate.empty_ranking_cases == 1
    )
    assert (
        report.aggregate.mean_precision_at_k
        == report.aggregate.mean_recall_at_k
        == 0.875
    )
    assert report.aggregate.mean_ndcg_at_k == pytest.approx(0.9032867981913646)
    assert (
        report.aggregate.evidence_checks == 35
        and report.aggregate.evidence_accuracy == 1
    )
    combined = next(item for item in report.ranking if item.key == "rank-combined")
    assert combined.recall_at_k == 0.5 and combined.relevant_count == 2


def test_digest_is_order_independent_for_json_objects_but_sensitive_to_labels():
    suite = load_suite()
    data = json.loads(json.dumps(suite.model_dump(mode="json"), sort_keys=True))
    assert suite_digest(EvaluationSuite.model_validate(data)) == suite_digest(suite)
    data["ranking"][0]["judgments"]["ada"] = 2
    assert suite_digest(EvaluationSuite.model_validate(data)) != suite_digest(suite)


@pytest.mark.parametrize(
    "kind,code",
    [
        ("hash", "SUITE_HASH_MISMATCH"),
        ("missing-case", "CASE_SET_MISMATCH"),
        ("extra-case", "CASE_SET_MISMATCH"),
        ("criteria", "CRITERIA_SET_MISMATCH"),
        ("revision", "PROFILE_REVISION_MISMATCH"),
    ],
)
def test_stale_or_incomplete_observations_cannot_be_scored(kind, code):
    data = load_example().model_dump(mode="json")
    if kind == "hash":
        data["suite_sha256"] = "0" * 64
    elif kind == "missing-case":
        data["ranking"].pop()
    elif kind == "extra-case":
        data["ranking"].append({"key": "unexpected", "ranked_ids": []})
    elif kind == "criteria":
        data["evidence"][0]["criteria"].pop()
    else:
        data["evidence"][0]["profile_revision"] = 2
    with pytest.raises(EvaluationDataError, match=code):
        evaluate(data)


@pytest.mark.parametrize(
    "kind,code",
    [
        ("foreign", "FORBIDDEN_RESULT"),
        ("unjudged", "UNJUDGED_RESULT"),
        ("empty", "EXPECTED_EMPTY"),
        ("proof", "INVALID_PROVENANCE"),
        ("rank-proof", "INVALID_PROVENANCE"),
        ("source", "SOURCE_STATUS_CHANGED"),
        ("recall", "BELOW_THRESHOLD"),
    ],
)
def test_quality_and_integrity_regressions_fail_the_gate(kind, code):
    data = load_example().model_dump(mode="json")
    if kind == "foreign":
        data["ranking"][0]["ranked_ids"].append("other-tenant")
    elif kind == "unjudged":
        data["ranking"][0]["ranked_ids"].append("unknown")
    elif kind == "empty":
        data["ranking"][-1]["ranked_ids"] = ["ada"]
    elif kind == "proof":
        data["evidence"][0]["criteria"][0]["provenance_valid"] = False
    elif kind == "rank-proof":
        data["ranking"][0]["provenance_failures"] = 1
    elif kind == "source":
        data["evidence"][0]["source_status"] = "indexed"
    else:
        data["ranking"][0]["ranked_ids"] = []
    report = evaluate(data)
    assert not report.gate_passed and code in {item.code for item in report.failures}


def test_evidence_false_positives_and_false_negatives_are_measured_separately():
    data = load_example().model_dump(mode="json")
    first = data["evidence"][0]["criteria"]
    first[0].update(found=False, provenance_valid=None)
    first[2].update(found=True, provenance_valid=True)
    report = evaluate(data)
    assert report.evidence[0].false_negative == report.evidence[0].false_positive == 1
    assert (
        report.aggregate.evidence_precision == report.aggregate.evidence_recall == 0.875
    )
    assert not report.gate_passed


def test_undefined_configured_metric_is_not_reported_as_a_pass():
    suite_data = load_suite().model_dump(mode="json")
    suite_data["ranking"], suite_data["evidence"], suite_data["criteria"] = (
        [suite_data["ranking"][-1]],
        [],
        [],
    )
    suite_data["thresholds"] = {"mean_recall_at_k": 0.0}
    suite = EvaluationSuite.model_validate(suite_data)
    data = load_example().model_dump(mode="json")
    data.update(
        suite_sha256=suite_digest(suite), ranking=[data["ranking"][-1]], evidence=[]
    )
    report = evaluate(data, suite)
    assert not report.gate_passed and report.failures[0].code == "UNDEFINED_METRIC"


def test_report_keeps_case_keys_and_metrics_without_source_text_or_item_ids():
    output = evaluate().model_dump_json()
    for hidden in (
        "ranked_ids",
        "judgments",
        "candidate_name",
        "document_id",
        "storage_key",
        "Python SQL",
        "@example.com",
    ):
        assert hidden not in output


def test_report_retains_the_corpus_fingerprint_and_observed_chunk_parameters():
    report = evaluate()
    assert report.corpus_sha256 == load_suite().corpus_sha256
    assert report.chunk_policies == load_example().chunk_policies
