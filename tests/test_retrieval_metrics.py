import pytest

from app.core.retrieval_metrics import (
    confusion_counts,
    defined_mean,
    evidence_rates,
    ranking_metrics,
)


def test_precision_uses_k_and_recall_uses_all_reference_relevant_items():
    result = ranking_metrics(["a"], {"a": 1, "b": 1}, k=2)
    assert result["precision_at_k"] == result["recall_at_k"] == 0.5
    assert result["returned_at_k"] == result["hits_at_k"] == 1
    assert result["ndcg_at_k"] == pytest.approx(0.6131471927654584)


def test_graded_ndcg_rewards_better_relevance_order():
    grades = {"a": 3, "b": 2, "c": 1}
    assert ranking_metrics(["a", "b", "c"], grades, k=3)["ndcg_at_k"] == 1
    reversed_value = ranking_metrics(["c", "b", "a"], grades, k=3)
    assert reversed_value["ndcg_at_k"] == pytest.approx(0.6806060567602009)
    assert reversed_value["precision_at_k"] == 1


def test_first_relevant_rank_is_cut_off_at_k():
    observed = ["negative", "a"]
    grades = {"negative": 0, "a": 1}
    assert ranking_metrics(observed, grades, k=1)["reciprocal_rank_at_k"] == 0
    assert ranking_metrics(observed, grades, k=2)["reciprocal_rank_at_k"] == 0.5


def test_empty_results_with_positive_reference_are_zero_metrics():
    result = ranking_metrics([], {"a": 1}, k=3)
    assert result["precision_at_k"] == result["recall_at_k"] == 0
    assert result["ndcg_at_k"] == result["reciprocal_rank_at_k"] == 0


def test_no_relevant_reference_does_not_invent_perfect_recall_or_ndcg():
    result = ranking_metrics([], {"a": 0}, k=3)
    assert result["precision_at_k"] == 0
    assert (
        result["recall_at_k"]
        is result["ndcg_at_k"]
        is result["reciprocal_rank_at_k"]
        is None
    )


def test_unjudged_results_are_nonrelevant_and_reported_even_after_k():
    result = ranking_metrics(["unknown", "a", "another"], {"a": 1}, k=2)
    assert result["unjudged_count"] == 2
    assert result["precision_at_k"] == 0.5 and result["reciprocal_rank_at_k"] == 0.5


@pytest.mark.parametrize("k", [0, -1, True, 1.5])
def test_invalid_cutoff_is_rejected(k):
    with pytest.raises(ValueError):
        ranking_metrics([], {}, k=k)


@pytest.mark.parametrize("grade", [-1, 4, True, 1.0])
def test_invalid_reference_grade_is_rejected(grade):
    with pytest.raises(ValueError):
        ranking_metrics(["a"], {"a": grade}, k=1)


def test_duplicates_cannot_inflate_metrics():
    with pytest.raises(ValueError):
        ranking_metrics(["a", "a"], {"a": 1}, k=2)


def test_confusion_matrix_and_rates_have_independent_expected_counts():
    counts = confusion_counts(
        {"tp": True, "fp": False, "fn": True, "tn": False},
        {"tp": True, "fp": True, "fn": False, "tn": False},
    )
    assert counts == {
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 1,
        "true_negative": 1,
    }
    assert evidence_rates(counts) == {
        "evidence_checks": 4,
        "evidence_precision": 0.5,
        "evidence_recall": 0.5,
        "evidence_accuracy": 0.5,
    }


def test_no_positive_predictions_has_undefined_precision_and_zero_recall():
    counts = confusion_counts({"a": True}, {"a": False})
    assert evidence_rates(counts)["evidence_precision"] is None
    assert evidence_rates(counts)["evidence_recall"] == 0


@pytest.mark.parametrize("observed", [{}, {"a": 1}, {"a": True, "extra": False}])
def test_missing_extra_or_nonboolean_evidence_is_rejected(observed):
    with pytest.raises(ValueError):
        confusion_counts({"a": True}, observed)


@pytest.mark.parametrize(
    "counts",
    [
        {},
        {
            "true_positive": -1,
            "false_positive": 0,
            "false_negative": 0,
            "true_negative": 0,
        },
    ],
)
def test_invalid_confusion_counts_are_rejected(counts):
    with pytest.raises(ValueError):
        evidence_rates(counts)


def test_mean_ignores_undefined_values_and_preserves_zero():
    assert defined_mean([None, 0.0, 1.0]) == 0.5
    assert defined_mean([None]) is None


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_mean_rejects_nonfinite_values(value):
    with pytest.raises(ValueError):
        defined_mean([value])
