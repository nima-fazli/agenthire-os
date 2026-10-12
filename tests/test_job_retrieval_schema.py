from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.job_search_profile import JobSearchProfile
from app.schemas.job_retrieval import (
    JobCandidatePage,
    JobCandidateQuery,
    JobSearchProfileRead,
    JobSearchProfileWrite,
)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"q": ""},
        {"q": " "},
        {"q": False},
        {"q": 123},
        {"q": "& |"},
        {"q": "x" * 257},
        {"q": "word " * 17},
        {"q": "py\x00thon"},
        {"q": "Python", "revision": 2},
        {"q": "Python", "user_id": str(uuid4())},
        {"q": "Python", "organization_id": str(uuid4())},
    ],
    ids=[
        "missing",
        "empty",
        "blank",
        "bool",
        "number",
        "operators",
        "long",
        "terms",
        "nul",
        "revision",
        "user",
        "tenant",
    ],
)
def test_invalid_profile_input_is_rejected(payload):
    with pytest.raises(ValidationError):
        JobSearchProfileWrite(**payload)


def test_query_preserves_literal_words_and_trims_edges():
    assert JobSearchProfileWrite(q="  Python OR SQL  ").q == "Python OR SQL"
    assert JobSearchProfileWrite(q="مهندس نرم افزار").q == "مهندس نرم افزار"


@pytest.mark.parametrize(
    "payload",
    [
        {"limit": 0},
        {"limit": 51},
        {"offset": -1},
        {"offset": 1001},
        {"applicants_only": "unknown"},
        {"q": "override"},
        {"job_id": str(uuid4())},
        {"score": 1},
    ],
    ids=["zero", "large", "negative", "offset", "bool", "query", "job", "score"],
)
def test_retrieval_accepts_only_bounded_pagination_and_applicant_filter(payload):
    with pytest.raises(ValidationError):
        JobCandidateQuery(**payload)


def test_profile_response_uses_q_and_hides_writer_identity():
    now = datetime.now(UTC)
    profile = JobSearchProfile(
        job_id=uuid4(),
        query_text="Python SQL",
        revision=1,
        updated_by_user_id=uuid4(),
        created_at=now,
        updated_at=now,
    )
    public = JobSearchProfileRead.model_validate(profile).model_dump()
    assert public["q"] == "Python SQL"
    assert "query_text" not in public and "updated_by_user_id" not in public


def test_empty_candidate_page_retains_profile_and_candidate_total():
    page = JobCandidatePage(
        job_id=uuid4(),
        q="Python",
        profile_revision=3,
        profile_updated_at=datetime.now(UTC),
        applicants_only=True,
        items=[],
        total=12,
        limit=10,
        offset=50,
    )
    assert page.total == 12 and page.items == []
    assert (
        page.score_kind == "text_relevance"
        and page.retrieval_version == "best-chunk-v1"
    )
