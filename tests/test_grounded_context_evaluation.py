import copy
import hashlib

import pytest

from scripts.grounded_explanations_evaluation import evaluate, load_reference


def observations():
    """Construct expected observations without calling production grounding."""
    reference = load_reference()
    rows = []
    for case in reference["cases"]:
        text = case["text"]
        citation = None if text is None else {
            "quote": text, "start_offset": 0, "end_offset": len(text),
            "document_id": "source-document", "chunk_set_id": "source-chunks",
            "quote_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "chunk_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
        rows.append({"case": case["key"], "status": "ok", "elapsed_ms": 1,
            "document_id": "source-document", "chunk_set_id": "source-chunks",
            "result": {"criteria": [
                {"key": "skill", "state": "mention_observed" if text else "no_evidence", "citation": citation},
                {"key": "missing", "state": "no_evidence", "citation": None}],
                "language": case["language"], "generator_used": text is not None,
                "model_digest": "a" * 64 if text else None,
                "explanation_version": "extractive-brief-v2", "prompt_version": "local-quote-selection-v2",
                "citation_policy": "assigned-chunk-context-v1"}})
    return reference, rows


def report(reference, rows):
    return evaluate(reference, rows, model_kind="fixture", model_digest="a" * 64, source_kind="example")


def test_independent_expected_context_passes_without_logging_private_text():
    reference, rows = observations()
    value = report(reference, rows)
    assert value["gate_passed"] and value["version"] == "grounded-quality-v2"
    assert "never used" not in str(value) and "watercolor" not in str(value)


@pytest.mark.parametrize("key,quote", [
    ("negated_en", "Python professionally"),
    ("negated_fa", "پایتون"),
    ("context_after", "Python appears on the form."),
    ("multiple_terms", "My hobby is watercolor painting."),
    ("english", "P"),
])
def test_correct_offsets_and_hashes_cannot_hide_lost_context(key, quote):
    reference, rows = observations()
    row = next(row for row in rows if row["case"] == key)
    original = next(case["text"] for case in reference["cases"] if case["key"] == key)
    citation = row["result"]["criteria"][0]["citation"]
    start = original.index(quote)
    citation.update(quote=quote, start_offset=start, end_offset=start + len(quote),
                    quote_sha256=hashlib.sha256(quote.encode()).hexdigest())
    assert not report(reference, rows)["gate_passed"]


@pytest.mark.parametrize("issue", ["duplicate", "unknown", "old_policy", "wrong_source_hash"])
def test_reference_identity_policy_and_source_hash_are_enforced(issue):
    reference, rows = observations()
    if issue == "duplicate":
        rows[1] = copy.deepcopy(rows[0])
        with pytest.raises(ValueError):
            report(reference, rows)
        return
    if issue == "unknown":
        reference["version"] = "grounded-reference-v1"
        with pytest.raises(ValueError):
            report(reference, rows)
        return
    if issue == "old_policy": rows[0]["result"]["citation_policy"] = "model-selected-substring"
    else: rows[0]["result"]["criteria"][0]["citation"]["source_text_sha256"] = "0" * 64
    assert not report(reference, rows)["gate_passed"]
