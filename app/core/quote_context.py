"""Validate a lexical anchor while preserving its complete assigned witness."""

import re
import unicodedata

CONTEXT_POLICY = "assigned-chunk-context-v1"
MAX_CONTEXT_CHARS = 4000
_ARABIC_MARKS = re.compile(r"[\u064b-\u065f\u0670\u06d6-\u06ed]")
_TERMS = re.compile(r"[^\W_]+(?:[+#]+)?", re.UNICODE)
_FOLD = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "\u200c": " ",
                       "\u200d": " ", "ـ": ""})


def lexical_terms(value: str) -> frozenset[str]:
    """A conservative quote guard, not a replacement for PostgreSQL search v1."""
    if not isinstance(value, str):
        raise TypeError("Quote input must be text.")
    value = unicodedata.normalize("NFKC", value).casefold().translate(_FOLD)
    return frozenset(_TERMS.findall(_ARABIC_MARKS.sub("", value)))


def assigned_context(source: str, anchor: str, query: str) -> str:
    """Return original source text; never cut context around an anchor."""
    if (not isinstance(source, str) or not 1 <= len(source) <= MAX_CONTEXT_CHARS
            or not isinstance(anchor, str) or not 1 <= len(anchor) <= 400
            or not anchor.strip() or not isinstance(query, str) or len(query) > 256):
        raise ValueError("The anchor must occur in a bounded assigned source.")

    def word(char: str) -> bool:
        return char.isalnum() or char in "_+#" or unicodedata.category(char).startswith("M")

    occurrences = re.finditer(re.escape(anchor), source)
    if not any(
        (match.start() == 0 or not word(anchor[0]) or not word(source[match.start() - 1]))
        and (match.end() == len(source) or not word(anchor[-1]) or not word(source[match.end()]))
        for match in occurrences
    ):
        raise ValueError("The anchor must not cut a source token.")
    required = lexical_terms(query)
    if not required or not required.issubset(lexical_terms(anchor)):
        raise ValueError("The anchor must contain every complete query term.")
    # Keeping the entire assigned chunk preserves negation before AND after the
    # model's selection without pretending to perform semantic entailment.
    return source
