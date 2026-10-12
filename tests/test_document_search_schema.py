from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.document_search import DocumentSearchHit, DocumentSearchQuery


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"q": ""},
        {"q": " "},
        {"q": True},
        {"q": 42},
        {"q": "x" * 257},
        {"q": "python", "limit": 0},
        {"q": "python", "limit": 51},
        {"q": "python", "offset": -1},
        {"q": "python", "offset": 1001},
        {"q": "python", "candidate_id": "invalid"},
        {"q": "python", "organization_id": str(uuid4())},
        {"q": "python", "score": 1},
    ],
    ids=[
        "missing",
        "empty",
        "whitespace",
        "bool",
        "number",
        "too-long",
        "zero-limit",
        "large-limit",
        "negative-offset",
        "large-offset",
        "bad-filter",
        "tenant-override",
        "score-override",
    ],
)
def test_invalid_search_input_is_rejected(payload: dict) -> None:
    with pytest.raises(ValidationError):
        DocumentSearchQuery(**payload)


def test_filters_and_page_bounds_are_typed() -> None:
    candidate, document = uuid4(), uuid4()
    data = DocumentSearchQuery(
        q="  Python  ",
        candidate_id=str(candidate),
        document_id=str(document),
        limit=50,
        offset=1000,
    )
    assert (
        data.q == "Python"
        and data.candidate_id == candidate
        and data.document_id == document
    )
    assert data.limit == 50 and data.offset == 1000


@pytest.mark.parametrize("score", [-0.1, 1.1, float("inf"), float("nan")])
def test_relevance_score_is_finite_and_bounded(score: float) -> None:
    with pytest.raises(ValidationError):
        DocumentSearchHit(
            document_id=uuid4(),
            candidate_id=uuid4(),
            candidate_name="Ada",
            filename="resume.pdf",
            chunk_set_id=uuid4(),
            chunk_position=0,
            start_offset=0,
            end_offset=10,
            text="Python SQL",
            chunk_sha256="a" * 64,
            source_document_sha256="b" * 64,
            source_text_sha256="c" * 64,
            score=score,
        )
