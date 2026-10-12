import pytest
from pydantic import ValidationError

from app.schemas.job_matching import (
    JobMatchProfileWrite,
    MatchCriterionInput,
    MatchEvidenceQuery,
)

VALID = {"key": "python", "label": "Python", "q": "Python", "importance": "required"}


@pytest.mark.parametrize(
    "bad",
    [
        {"key": ""},
        {"key": "Python"},
        {"key": "x" * 41},
        {"key": "../key"},
        {"label": " "},
        {"label": "x" * 101},
        {"label": "bad\x00label"},
        {"label": "\ud800"},
        {"q": " "},
        {"q": True},
        {"q": 123},
        {"q": "& |"},
        {"q": "x" * 257},
        {"q": "word " * 17},
        {"q": "py\x00thon"},
        {"importance": "optional"},
        {"position": 1},
        {"score": 1},
        {"weight": 10},
    ],
    ids=[
        "empty-key",
        "upper-key",
        "long-key",
        "path-key",
        "blank-label",
        "long-label",
        "control-label",
        "surrogate",
        "blank-q",
        "bool-q",
        "number-q",
        "operators",
        "long-q",
        "terms",
        "control-q",
        "importance",
        "position",
        "score",
        "weight",
    ],
)
def test_invalid_or_client_owned_criterion_fields_are_rejected(bad):
    with pytest.raises(ValidationError):
        MatchCriterionInput(**(VALID | bad))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"criteria": []},
        {"criteria": [VALID] * 11},
        {"criteria": [VALID, VALID]},
        {"criteria": [VALID], "revision": 4},
        {"criteria": [VALID], "organization_id": "override"},
        {"criteria": [VALID], "user_id": "override"},
    ],
    ids=["missing", "empty", "too-many", "duplicates", "revision", "tenant", "user"],
)
def test_profile_is_bounded_and_keys_are_unique(payload):
    with pytest.raises(ValidationError):
        JobMatchProfileWrite(**payload)


def test_criteria_trim_text_keep_literal_query_and_allow_persian_labels():
    item = MatchCriterionInput(
        **(VALID | {"label": "  برنامه‌نویسی پایتون  ", "q": "  Python OR SQL  "})
    )
    assert item.label == "برنامه‌نویسی پایتون" and item.q == "Python OR SQL"
    values = [VALID | {"key": f"skill_{i}"} for i in range(10)]
    assert len(JobMatchProfileWrite(criteria=values).criteria) == 10


@pytest.mark.parametrize(
    "payload",
    [{"q": "override"}, {"revision": 2}, {"score": 1}, {"candidate_id": "override"}],
)
def test_read_evidence_query_cannot_override_saved_criteria_or_identity(payload):
    with pytest.raises(ValidationError):
        MatchEvidenceQuery(**payload)
