import hashlib

import pytest

from app.core.grounded_explanations import ExplanationFailure, ground, prepare
from app.core.quote_context import assigned_context
from scripts.grounded_explanations_evaluation import example_snapshot


@pytest.mark.parametrize("text,anchor,query", [
    ("I have never used Python professionally.", "Python professionally", "Python"),
    ("Python appears here. I have not used it professionally.", "Python", "Python"),
    ("من هرگز با پایتون کار نکرده‌ام.", "پایتون", "پایتون"),
    ("من با پايتون كار نكرده‌ام.", "پايتون", "پایتون"),
    ("I use Python with SQL.", "Python with SQL", "Python SQL"),
    ("I maintain C++ services, not C# services.", "C++", "C++"),
    ("I built Ｐｙｔｈｏｎ APIs.", "Ｐｙｔｈｏｎ", "Python"),
])
def test_context_preserves_original_negation_spelling_and_surrounding_sentences(text, anchor, query):
    assert assigned_context(text, anchor, query) == text


@pytest.mark.parametrize("text,anchor,query", [
    ("I use Python. My hobby is painting.", "My hobby is painting.", "Python"),
    ("I use Python APIs.", "P", "Python"),
    ("Pythonic conventions only.", "Python", "Python"),
    ("I use Python with SQL.", "Python", "Python SQL"),
    ("I use C#.", "C#", "C++"),
    ("I use C+++.", "C++", "C++"),
    ("I use Python APIs.", "Rust", "Python"),
    ("I use Python APIs.", " ", "Python"),
    ("I use Python APIs.", "Python", "!!!"),
])
def test_irrelevant_invented_or_partial_word_anchors_fail(text, anchor, query):
    with pytest.raises(ValueError):
        assigned_context(text, anchor, query)


def test_context_is_bounded_even_when_the_anchor_is_short():
    with pytest.raises(ValueError):
        assigned_context("Python " + "x" * 4000, "Python", "Python")


def test_ground_keeps_absolute_unicode_offsets_and_full_context_hash():
    text = "😀 I have never used Python professionally."
    snapshot = example_snapshot({"q": "Python", "text": text})
    snapshot.criteria[0].evidence.start_offset = 100
    snapshot.criteria[0].evidence.end_offset = 100 + len(text)
    assignments, _, _ = prepare(snapshot)
    result = ground({"quotes": [{"criterion": "skill", "source": "s0", "quote": "Python"}]}, assignments)["skill"]
    assert (result.start_offset, result.end_offset) == (100, 100 + len(text))
    assert result.quote == text
    assert result.quote_sha256 == hashlib.sha256(text.encode()).hexdigest()


def test_ground_rejects_a_source_local_but_unrelated_quote():
    snapshot = example_snapshot({"q": "Python", "text": "Python APIs. My hobby is watercolor painting."})
    assignments, _, _ = prepare(snapshot)
    with pytest.raises(ExplanationFailure, match="OUTPUT_UNGROUNDED"):
        ground({"quotes": [{"criterion": "skill", "source": "s0", "quote": "watercolor painting"}]}, assignments)
