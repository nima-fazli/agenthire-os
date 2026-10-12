import re

import pytest
from sqlalchemy import column, select
from sqlalchemy.dialects import postgresql

from app.core.text_search import search_query, search_vector, validate_search_query


@pytest.mark.parametrize(
    "value",
    [
        "Python SQL",
        "مهندس نرم افزار",
        "مهندس\u200cنرم\u200cافزار",
        "كَيَان",
        "CAFÉ",
        "２０２６",
        "C++",
        "  Python\nSQL\t ",
    ],
)
def test_query_validation_preserves_literal_text(value: str) -> None:
    assert validate_search_query(value) == value.strip()


@pytest.mark.parametrize(
    "value",
    ["", " ", "| & !", "\u0640\u0640", "\u064b\u064c", "___"],
    ids=["empty", "space", "operators", "tatweel", "marks", "underscores"],
)
def test_non_searchable_queries_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="word or number"):
        validate_search_query(value)


@pytest.mark.parametrize(
    "value",
    ["py\x00thon", "\x1fpython", "python\ud800"],
    ids=["nul", "control", "surrogate"],
)
def test_unsupported_unicode_controls_never_reach_postgres(value: str) -> None:
    with pytest.raises(ValueError, match="control characters"):
        validate_search_query(value)


@pytest.mark.parametrize(
    "value",
    ["x" * 257, "word " * 17, "\ufdfa" * 20],
    ids=["characters", "terms", "normalization-expansion"],
)
def test_work_budget_is_bounded(value: str) -> None:
    with pytest.raises(ValueError, match="size or term limit"):
        validate_search_query(value)


def test_query_is_bound_as_data_and_uses_plain_text_search() -> None:
    value = "python'); DROP TABLE users; --"
    statement = select(search_vector(column("text")), search_query(value))
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "plainto_tsquery" in sql and re.search(r"\bto_tsquery\(", sql) is None
    assert "'simple'::regconfig" in sql
    assert sql.count("agenthire_search_text_v1(") == 2
    assert value not in sql and value in statement.compile().params.values()
