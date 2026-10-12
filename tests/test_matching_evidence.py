import pytest

from app.core.matching_evidence import MATCHING_VERSION, summarize_evidence


@pytest.mark.parametrize(
    "ready,indexed,status",
    [
        (0, 0, "no_documents"),
        (2, 0, "not_indexed"),
        (2, 1, "partial"),
        (2, 2, "indexed"),
    ],
)
def test_source_readiness_is_reported_separately_from_criterion_coverage(
    ready, indexed, status
):
    summary = summarize_evidence(
        [("required", False), ("preferred", False)],
        ready_documents=ready,
        indexed_documents=indexed,
    )
    assert summary == {
        "required_total": 1,
        "required_with_evidence": 0,
        "preferred_total": 1,
        "preferred_with_evidence": 0,
        "ready_documents": ready,
        "indexed_documents": indexed,
        "source_status": status,
    }


def test_required_and_preferred_evidence_counts_do_not_mix_or_create_a_fit_score():
    summary = summarize_evidence(
        [("required", True), ("required", False), ("preferred", True)],
        ready_documents=1,
        indexed_documents=1,
    )
    assert (summary["required_total"], summary["required_with_evidence"]) == (2, 1)
    assert (summary["preferred_total"], summary["preferred_with_evidence"]) == (1, 1)
    assert "score" not in summary and MATCHING_VERSION == "criterion-evidence-v1"


def test_all_preferred_criteria_keep_a_valid_zero_required_total():
    summary = summarize_evidence(
        [("preferred", True)], ready_documents=1, indexed_documents=1
    )
    assert summary["required_total"] == summary["required_with_evidence"] == 0


@pytest.mark.parametrize("ready,indexed", [(-1, 0), (1, -1), (1, 2)])
def test_inconsistent_source_counts_are_rejected(ready, indexed):
    with pytest.raises(ValueError):
        summarize_evidence([], ready_documents=ready, indexed_documents=indexed)


@pytest.mark.parametrize("outcome", [("unknown", True), ("required", "yes")])
def test_invalid_evidence_outcomes_are_rejected(outcome):
    with pytest.raises(ValueError):
        summarize_evidence([outcome], ready_documents=1, indexed_documents=1)


def test_missing_index_cannot_be_reported_as_found_evidence():
    with pytest.raises(ValueError):
        summarize_evidence([("required", True)], ready_documents=1, indexed_documents=0)
