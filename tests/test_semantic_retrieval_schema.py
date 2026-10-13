import pytest
from pydantic import ValidationError

from app.schemas.semantic_retrieval import SemanticDocumentQuery, SemanticJobQuery


@pytest.mark.parametrize("changes", [
    {"q": "!!!"}, {"q": "x\x00"}, {"q": " "}, {"q": "x" * 257},
    {"mode": "cloud"}, {"limit": True}, {"limit": 51}, {"limit": "2"},
    {"min_similarity": -0.1}, {"min_similarity": float("nan")},
    {"model_tag": "external"}, {"offset": 1},
])
def test_document_queries_are_bounded_and_server_model_is_not_client_owned(changes):
    with pytest.raises(ValidationError):
        SemanticDocumentQuery.model_validate({"q": "Python"} | changes)


@pytest.mark.parametrize("changes", [{"q": "replace profile"}, {"applicants_only": "true"}, {"applicants_only": 1}])
def test_job_query_uses_saved_profile_and_strict_applicant_filter(changes):
    with pytest.raises(ValidationError):
        SemanticJobQuery.model_validate(changes)


def test_default_hybrid_query_preserves_persian_and_explicit_threshold():
    value = SemanticDocumentQuery(q=" مهندس پایگاه داده ", min_similarity=0.4)
    assert value.q == "مهندس پایگاه داده" and value.mode == "hybrid" and value.limit == 10
