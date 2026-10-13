from uuid import UUID

import pytest

from app.core.semantic_retrieval import EVIDENCE_FIELDS, fuse, query_input


def row(candidate, branch, score=0.8, document=None):
    result = dict.fromkeys(EVIDENCE_FIELDS)
    result.update(candidate_id=UUID(int=candidate), candidate_name=str(candidate),
                  document_id=UUID(int=document or candidate), chunk_set_id=UUID(int=candidate),
                  chunk_position=0, branch=branch, score=score)
    return result


def test_rrf_keeps_independent_witnesses_and_does_not_reward_duplicate_resumes():
    rows = [row(1, "lexical", document=1), row(1, "lexical", document=2),
            row(2, "lexical"), row(2, "semantic"), row(1, "semantic", document=3)]
    result = fuse(rows, mode="hybrid", candidates=True)
    assert len(result) == 2 and result[0]["candidate_id"] == UUID(int=1)
    assert result[1]["lexical_rank"] == 2
    assert len(result[0]["evidence"]) == 2
    assert {item["document_id"] for item in result[0]["evidence"]} == {UUID(int=1), UUID(int=3)}


def test_semantic_scores_and_ties_are_stable_and_chunk_search_keeps_distinct_documents():
    rows = [row(2, "semantic", 0.5), row(1, "semantic", 0.5), row(1, "lexical", 1)]
    result = fuse(rows, mode="semantic", candidates=True)
    assert [item["candidate_id"].int for item in result] == [1, 2]
    assert all(item["score"] == 0.5 and item["lexical_rank"] is None for item in result)
    assert len(fuse([row(1, "semantic", document=1), row(1, "semantic", document=2)],
                    mode="hybrid", candidates=False)) == 2
    assert query_input("رزومه") == "Instruct: Retrieve resume passages relevant to this job requirement.\nQuery: رزومه"


@pytest.mark.parametrize("branch,score", [("other", 1), ("semantic", float("nan")), ("lexical", float("inf"))])
def test_invalid_observations_are_rejected(branch, score):
    with pytest.raises(ValueError):
        fuse([row(1, branch, score)], mode="hybrid", candidates=True)
