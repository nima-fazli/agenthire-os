import copy
import json

import pytest

from app.core.grounded_explanations import (
    ExplanationFailure,
    fingerprint,
    ground,
    prepare,
    render,
    strict_json,
)
from scripts.grounded_explanations_evaluation import (
    evaluate,
    example_snapshot,
    load_reference,
)


def test_quote_is_exact_and_deduplicated_prompt_contains_no_identity_metadata():
    snapshot = example_snapshot()
    assignments, messages, schema = prepare(snapshot)
    assert len(assignments) == 1 and schema["properties"]["quotes"]["minItems"] == 1
    assert "Synthetic" not in messages[1]["content"] and "synthetic.pdf" not in messages[1]["content"]
    quote = "Python APIs"
    citations = ground({"quotes": [{"criterion": "skill", "source": "s0", "quote": quote}]}, assignments)
    citation = citations["skill"]
    assert snapshot.criteria[0].evidence.text[citation.start_offset:citation.end_offset] == quote
    assert render(snapshot, citations, "fa")["criteria"][0]["state"] == "mention_observed"
    assert render(snapshot, citations, "en")["criteria"][1]["state"] == "no_evidence"


@pytest.mark.parametrize("change", ["fabricated", "source", "criterion", "duplicate", "extra", "blank"])
def test_model_cannot_invent_claims_sources_or_criterion_coverage(change):
    assignments, _, _ = prepare(example_snapshot())
    choice = {"criterion": "skill", "source": "s0", "quote": "Python"}
    payload = {"quotes": [choice]}
    if change == "fabricated": choice["quote"] = "MIT degree"
    elif change == "source": choice["source"] = "s9"
    elif change == "criterion": choice["criterion"] = "missing"
    elif change == "duplicate": payload["quotes"].append(choice.copy())
    elif change == "extra": payload["summary"] = "Hire immediately"
    else: choice["quote"] = " "
    with pytest.raises(ExplanationFailure):
        ground(payload, assignments)


@pytest.mark.parametrize("raw", ['{"quotes":[],"quotes":[]}', '{"a":NaN}', '{"a":Infinity}', 'invalid'])
def test_ambiguous_or_nonfinite_json_is_rejected(raw):
    with pytest.raises(ValueError):
        strict_json(raw)


def test_fingerprint_ignores_observation_time_but_pins_profile_and_source():
    snapshot = example_snapshot()
    assert fingerprint(snapshot) == fingerprint(snapshot.model_copy(update={"observed_at": snapshot.observed_at.replace(year=2027)}))
    assert fingerprint(snapshot) != fingerprint(snapshot.model_copy(update={"profile_revision": 2}))
    snapshot.criteria[0].evidence.text += " changed"
    with pytest.raises(ExplanationFailure, match="SOURCE_INVALID"):
        prepare(snapshot)


def test_prompt_budget_rejects_large_unicode_sources_instead_of_slicing():
    case = {"text": "پایتون " * 600, "q": "پایتون"}
    with pytest.raises(ExplanationFailure, match="INPUT_TOO_LARGE"):
        prepare(example_snapshot(case))


def test_no_evidence_requires_no_model_and_negation_remains_visible():
    empty = example_snapshot(load_reference()["cases"][-1])
    assert prepare(empty) == ({}, None, None)
    snapshot = example_snapshot({"q": "Python", "text": "I have never used Python professionally."})
    assignments, _, _ = prepare(snapshot)
    citations = ground({"quotes": [{"criterion": "skill", "source": "s0", "quote": snapshot.criteria[0].evidence.text}]}, assignments)
    result = render(snapshot, citations, "en")
    assert "never used" in result["criteria"][0]["text"] and "does not establish proficiency" in result["scope_note"]


def test_two_criteria_share_one_source_but_keep_independent_quotes_and_offsets():
    snapshot = example_snapshot()
    snapshot.criteria[1].q = "PostgreSQL"
    snapshot.criteria[1].evidence = snapshot.criteria[0].evidence.model_copy()
    assignments, messages, schema = prepare(snapshot)
    assert len(json.loads(messages[1]["content"])["sources"]) == 1
    assert schema["properties"]["quotes"]["minItems"] == 2
    citations = ground({"quotes": [{"criterion": "skill", "source": "s0", "quote": "Python"},
                                   {"criterion": "missing", "source": "s0", "quote": "PostgreSQL"}]}, assignments)
    assert citations["skill"].start_offset < citations["missing"].start_offset
    assert citations["skill"].document_id == citations["missing"].document_id


def observations():
    reference = load_reference()
    rows = []
    for case in reference["cases"]:
        snapshot = example_snapshot(case)
        assignments, _, _ = prepare(snapshot)
        citations = ground({"quotes": [{"criterion": "skill", "source": "s0", "quote": case["q"]}]}, assignments) if assignments else {}
        result = render(snapshot, citations, case["language"])
        result = json.loads(json.dumps(result, default=lambda value: value.model_dump(mode="json") if hasattr(value, "model_dump") else str(value)))
        result.update(language=case["language"], generator_used=bool(assignments), model_digest="a" * 64 if assignments else None)
        rows.append({"case": case["key"], "status": "ok", "elapsed_ms": 1.0, "result": result,
                     "document_id": str(snapshot.criteria[0].evidence.document_id) if assignments else None,
                     "chunk_set_id": str(snapshot.criteria[0].evidence.chunk_set_id) if assignments else None})
    return reference, rows


def test_independent_reference_gate_records_provenance_and_redacts_source_text():
    reference, rows = observations()
    report = evaluate(reference, rows, model_kind="fixture", model_digest="a" * 64, source_kind="example")
    assert report["gate_passed"] and report["source_kind"] == "example"
    assert "quote" not in json.dumps(report) and "Python" not in json.dumps(report)


@pytest.mark.parametrize("issue", ["wrong_source", "invented_missing", "bad_range", "rejected_normal"])
def test_reference_gate_detects_grounding_and_coverage_regressions(issue):
    reference, rows = observations()
    value = rows[0]
    if issue == "wrong_source": value["document_id"] = "foreign"
    elif issue == "invented_missing": value["result"]["criteria"][1]["citation"] = copy.deepcopy(value["result"]["criteria"][0]["citation"])
    elif issue == "bad_range": value["result"]["criteria"][0]["citation"]["end_offset"] += 1
    else: value.update(status="rejected", code="EXPLANATION_OUTPUT_INVALID")
    assert not evaluate(reference, rows, model_kind="live", model_digest="a" * 64, source_kind="example")["gate_passed"]
