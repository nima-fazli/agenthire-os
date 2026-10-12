import pytest
from pydantic import ValidationError

from app.schemas.retrieval_evaluation import (
    EvaluationObservations,
    EvaluationSuite,
    ObservedCriterion,
    RankingCase,
    RankingObservation,
)
from scripts.evaluation_cases import load_example, load_suite


@pytest.mark.parametrize(
    "change",
    [
        {"key": "../case"},
        {"q": " "},
        {"k": 0},
        {"k": 51},
        {"k": True},
        {"judgments": {}},
        {"judgments": {"a": True}},
        {"judgments": {"a": 4}},
        {"forbidden": ["a"]},
        {"forbidden": ["b", "b"]},
        {"score": 1},
    ],
    ids=[
        "path",
        "q",
        "zero",
        "limit",
        "bool",
        "empty",
        "bool-grade",
        "grade",
        "positive-forbidden",
        "duplicate-forbidden",
        "extra",
    ],
)
def test_bad_ranking_case_is_rejected(change):
    payload = {"key": "case", "q": "Python", "k": 2, "judgments": {"a": 1, "b": 0}}
    with pytest.raises(ValidationError):
        RankingCase.model_validate(payload | change)


@pytest.mark.parametrize(
    "change",
    [
        {"found": 1},
        {"found": True, "provenance_valid": None},
        {"found": False, "provenance_valid": True},
        {"provenance_valid": "yes"},
    ],
    ids=["bool", "missing-proof", "unfound-proof", "proof-type"],
)
def test_observed_provenance_contract_is_strict(change):
    with pytest.raises(ValidationError):
        ObservedCriterion.model_validate(
            {"key": "python", "found": True, "provenance_valid": True} | change
        )


def test_duplicate_results_and_oversized_observations_are_rejected():
    for values in (["a", "a"], [f"item-{i}" for i in range(201)]):
        with pytest.raises(ValidationError):
            RankingObservation(key="case", ranked_ids=values)


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate-cases",
        "duplicate-criteria",
        "missing-criterion",
        "bool-label",
        "no-thresholds",
        "nan-threshold",
        "empty-suite",
        "too-many-cases",
    ],
)
def test_suite_rejects_inconsistent_or_unbounded_reference_data(kind):
    data = load_suite().model_dump(mode="json")
    if kind == "duplicate-cases":
        data["ranking"].append(data["ranking"][0])
    elif kind == "duplicate-criteria":
        data["criteria"].append(data["criteria"][0])
    elif kind == "missing-criterion":
        data["evidence"][0]["expected"].pop("sql")
    elif kind == "bool-label":
        data["evidence"][0]["expected"]["sql"] = 1
    elif kind == "no-thresholds":
        data["thresholds"] = {}
    elif kind == "nan-threshold":
        data["thresholds"]["mean_recall_at_k"] = float("nan")
    elif kind == "empty-suite":
        data["ranking"], data["evidence"] = [], []
    else:
        data["ranking"] = [data["ranking"][0]] * 101
    with pytest.raises(ValidationError):
        EvaluationSuite.model_validate(data)


@pytest.mark.parametrize("kind", ["hash", "source", "duplicates", "extra"])
def test_observation_identity_and_origin_are_validated(kind):
    data = load_example().model_dump(mode="json")
    if kind == "hash":
        data["suite_sha256"] = "invalid"
    elif kind == "source":
        data["source_kind"] = "certified"
    elif kind == "duplicates":
        data["evidence"].append(data["evidence"][0])
    else:
        data["private_resume_text"] = "private"
    with pytest.raises(ValidationError):
        EvaluationObservations.model_validate(data)


@pytest.mark.parametrize("kind", ["overlap", "duplicate-policy", "missing-policy"])
def test_actual_chunk_policy_metadata_is_bounded_and_unambiguous(kind):
    data = load_example().model_dump(mode="json")
    if kind == "overlap":
        data["chunk_policies"][0]["overlap_chars"] = data["chunk_policies"][0][
            "max_chars"
        ]
    elif kind == "duplicate-policy":
        data["chunk_policies"].append(data["chunk_policies"][0])
    else:
        data["chunk_policies"] = []
    with pytest.raises(ValidationError):
        EvaluationObservations.model_validate(data)
