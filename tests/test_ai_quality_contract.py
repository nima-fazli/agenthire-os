import json

import pytest
from pydantic import ValidationError

from scripts.ai_quality_contract import Reference, load_reference, reference_digest


def test_reference_has_complete_blind_judgments_and_bilingual_cases():
    reference = load_reference()
    assert len(reference.resumes) == 12 and len(reference.queries) == 8 and len(reference.briefs) == 12
    assert all(len(query.grades) == 12 for query in reference.queries)
    assert {case.kind for case in reference.briefs} == {"quote", "attack", "no_evidence", "oversized"}
    assert {case.language for case in reference.queries} == {"fa", "en"}


@pytest.mark.parametrize("mutation", ["missing_grade", "extra_grade", "duplicate", "bool_grade", "changed_pair", "same_name"])
def test_bad_reference_is_rejected(mutation):
    data = load_reference().model_dump()
    if mutation == "missing_grade":
        del data["queries"][0]["grades"]["artist"]
    elif mutation == "extra_grade":
        data["queries"][0]["grades"]["unseen"] = 0
    elif mutation == "duplicate":
        data["queries"][1]["key"] = data["queries"][0]["key"]
    elif mutation == "bool_grade":
        data["queries"][0]["grades"]["artist"] = True
    elif mutation == "changed_pair":
        data["resumes"][1]["text"] += " Changed."
    else:
        data["resumes"][1]["name"] = data["resumes"][0]["name"]
    with pytest.raises(ValidationError):
        Reference.model_validate(data)


def test_reference_identity_ignores_json_layout_but_tracks_judgments(tmp_path):
    data = load_reference().model_dump()
    path = tmp_path / "reference.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8-sig")
    assert reference_digest(load_reference(path)) == reference_digest(load_reference())
    data["queries"][0]["grades"]["artist"] = 1
    assert reference_digest(Reference.model_validate(data)) != reference_digest(load_reference())


def test_duplicate_json_keys_and_nonfinite_values_are_rejected(tmp_path):
    path = tmp_path / "invalid.json"
    for value in ('{"version":1,"version":2}', '{"value":NaN}'):
        path.write_text(value)
        with pytest.raises(ValueError):
            load_reference(path)


def test_oversized_case_exercises_utf8_budget_without_exceeding_chunk_contract():
    case = next(c for c in load_reference().briefs if c.kind == "oversized")
    assert len(case.context) <= 4000
    assert len(case.context.encode()) > 6000
