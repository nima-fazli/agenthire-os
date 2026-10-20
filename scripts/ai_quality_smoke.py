"""Serial test-database reference evaluation; live models use authenticated HTTP."""

import argparse
import asyncio
import json
import os
import re
import time

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.grounded_explanations import ExplanationFailure
from app.core.local_chat import LocalChatGenerator
from app.core.local_embeddings import LocalEmbeddingEncoder
from app.core.semantic_embeddings import EmbeddingFailure
from app.db.session import async_session_factory, engine
from app.schemas.grounded_explanations import ExplanationRequest, GroundedExplanation
from app.schemas.job_matching import JobMatchProfileRead, JobMatchProfileWrite
from app.schemas.job_retrieval import (
    JobCandidatePage,
    JobCandidateQuery,
    JobSearchProfileRead,
    JobSearchProfileWrite,
)
from app.schemas.semantic_retrieval import SemanticJobQuery, SemanticPage
from app.services.grounded_explanations import GroundedExplanationService
from app.services.job_matching import JobMatchingService
from app.services.job_retrieval import JobRetrievalService
from app.services.semantic_retrieval import SemanticRetrievalService
from scripts.ai_quality_contract import MODES, REPETITIONS, load_reference
from scripts.ai_quality_fixture import (
    FixtureEncoder,
    FixtureGenerator,
    QualityFixture,
    require_test_database,
    verify_source,
)
from scripts.ai_quality_http import QualityHTTP
from scripts.ai_quality_metrics import evaluate


def job_path(fixture, *, brief=False):
    scope = fixture.scope(brief=brief)
    return f"/organizations/{scope['organization_id']}/jobs/{scope['job_id']}"


def ranking_observation(page, mode, fixture, profile, digest):
    semantic = mode != "lexical"
    page = (SemanticPage if semantic else JobCandidatePage).model_validate(page)
    expected = fixture.scope()
    valid = (page.job_id == expected["job_id"] and page.profile_revision == profile.revision
             and page.profile_updated_at == profile.updated_at and not page.applicants_only and page.limit == 12)
    if semantic:
        valid = valid and (page.model_digest == digest and page.mode == mode and page.unit == "candidate"
            and not page.pool_truncated and page.eligible_chunks == page.embedded_chunks == 12
            and page.score_kind == ("cosine_similarity" if mode == "semantic" else "reciprocal_rank_fusion"))
    else:
        valid = valid and page.q == profile.q and page.offset == 0 and page.total >= len(page.items)
    keys = {value: key for key, value in fixture.candidates.items() if key in {r.key for r in fixture.reference.resumes}}
    ranking, scores = [], []
    for hit in page.items:
        key = keys.get(hit.candidate_id)
        if key is None:
            return {"valid": False, "code": "SOURCE_SCOPE_FAILED", "ranking": [], "scores": [],
                    "model_digest": page.model_digest if semantic else None}
        ranking.append(key)
        scores.append(hit.score)
        for evidence in (hit.evidence if semantic else [hit]):
            witness = fixture.witnesses[key]
            valid = valid and evidence.candidate_id == hit.candidate_id and verify_source(evidence, witness)
            if semantic:
                valid = valid and evidence.embedding_job_id == (witness["embedding_job_id"] if evidence.branch == "semantic" else None)
    valid = valid and len(ranking) == len(set(ranking))
    return {"valid": bool(valid), "code": "OK" if valid else "SOURCE_PROVENANCE_FAILED",
            "ranking": ranking, "scores": scores, "model_digest": page.model_digest if semantic else None}


def brief_observation(payload, case, fixture, profile, digest):
    page = GroundedExplanation.model_validate(payload)
    valid = (page.job_id == fixture.brief_job and page.candidate_id == fixture.candidates[case.key]
             and page.language == case.language and page.profile_revision == profile.revision
             and page.profile_updated_at == profile.updated_at and [c.key for c in page.criteria] == ["skill", "missing"])
    for criterion in page.criteria:
        witnessed = criterion.key == "skill" and case.kind in {"quote", "attack"}
        valid = valid and criterion.q == (case.q if criterion.key == "skill" else "Rust")
        if witnessed:
            valid = valid and criterion.state == "mention_observed" and criterion.citation is not None and criterion.evidence is not None
            if criterion.evidence is not None:
                valid = valid and criterion.evidence.candidate_id == page.candidate_id and verify_source(criterion.evidence, fixture.witnesses[case.key])
            if criterion.citation is not None:
                valid = valid and verify_source(criterion.citation, fixture.witnesses[case.key], citation=True)
                valid = valid and criterion.citation.quote == case.context and criterion.citation.quote in criterion.text
        else:
            valid = valid and criterion.state == "no_evidence" and criterion.citation is None and criterion.evidence is None
        label = "Source mention" if criterion.key == "skill" else "Rust"
        if case.language == "fa":
            expected = (f"برای معیار «{label}»، این عبارت در منبع آمده است: «{case.context}»." if witnessed else
                        f"برای معیار «{label}»، در منابع قابل جست‌وجوی فعلی شاهدی یافت نشد.")
        else:
            expected = (f'For "{label}", the source states: "{case.context}".' if witnessed else
                        f'No evidence for "{label}" was found in the currently searchable sources.')
        valid = valid and criterion.text == expected and criterion.label == label
    generated = case.kind in {"quote", "attack"}
    valid = valid and page.generator_used == generated
    if generated:
        valid = valid and page.model_digest == digest
    valid = valid and (page.summary.required_total, page.summary.required_with_evidence,
                       page.summary.preferred_total, page.summary.preferred_with_evidence) == (1, int(generated), 1, 0)
    return {"valid": bool(valid), "code": "OK" if valid else "CITATION_PROVENANCE_FAILED",
            "model_digest": page.model_digest, "input_tokens": page.input_tokens, "output_tokens": page.output_tokens}


def rejected_observation(status, payload, case):
    code = payload.get("error", {}).get("code", "QUALITY_REQUEST_FAILED")
    if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code):
        code = "QUALITY_REQUEST_FAILED"
    valid = (case.kind == "oversized" and status == 422 and code == "EXPLANATION_INPUT_TOO_LARGE") or (
        case.kind == "attack" and status == 503 and code in {"EXPLANATION_OUTPUT_INVALID", "EXPLANATION_OUTPUT_UNGROUNDED"})
    return {"valid": valid, "code": code}


async def collect(reference, fixture, factory, settings, encoder, generator, digest, *, live=False):
    client = QualityHTTP(fixture.token) if live else None
    rows = []
    async with factory() as session:
        lexical = JobRetrievalService(session, settings)
        semantic = SemanticRetrievalService(session, settings, encoder)
        matching = JobMatchingService(session, settings)
        explanation = GroundedExplanationService(session, settings, generator)
        for repeat in range(1, REPETITIONS + 1):
            for query in reference.queries:
                if live:
                    status, data = await client.call("PUT", job_path(fixture) + "/search-profile", {"q": query.q})
                    if status != 200:
                        raise ValueError("quality_profile_write_failed")
                    profile = JobSearchProfileRead.model_validate(data)
                else:
                    profile = await lexical.put_profile(JobSearchProfileWrite(q=query.q), **fixture.scope())
                for mode in MODES:
                    started = time.monotonic()
                    if live:
                        path = job_path(fixture) + ("/candidate-retrieval?limit=12" if mode == "lexical" else "/semantic-candidate-retrieval")
                        status, page = await client.call("GET" if mode == "lexical" else "POST", path,
                                                        None if mode == "lexical" else {"mode": mode, "limit": 12})
                        if status != 200:
                            raise ValueError("quality_retrieval_failed")
                    else:
                        page = (await lexical.retrieve(JobCandidateQuery(limit=12), **fixture.scope()) if mode == "lexical"
                                else await semantic.search(SemanticJobQuery(mode=mode, limit=12), **fixture.scope()))
                    elapsed = (time.monotonic() - started) * 1000
                    result = ranking_observation(page, mode, fixture, profile, digest[0])
                    rows.append({"family": "ranking", "case": query.key, "mode": mode, "repetition": repeat,
                                 "elapsed_ms": elapsed, **result})
                    await session.rollback()
            for case in reference.briefs:
                criteria = [{"key": "skill", "label": "Source mention", "q": case.q, "importance": "required"},
                            {"key": "missing", "label": "Rust", "q": "Rust", "importance": "preferred"}]
                if live:
                    status, data = await client.call("PUT", job_path(fixture, brief=True) + "/match-profile", {"criteria": criteria})
                    if status != 200:
                        raise ValueError("quality_profile_write_failed")
                    profile = JobMatchProfileRead.model_validate(data)
                else:
                    profile = await matching.put_profile(JobMatchProfileWrite(criteria=criteria), **fixture.scope(brief=True))
                started = time.monotonic()
                if live:
                    status, payload = await client.call("POST", job_path(fixture, brief=True) +
                        f"/candidates/{fixture.candidates[case.key]}/grounded-explanation", {"language": case.language})
                else:
                    try:
                        payload = await explanation.explain(ExplanationRequest(language=case.language),
                            candidate_id=fixture.candidates[case.key], **fixture.scope(brief=True))
                        status = 200
                    except AppError as error:
                        status, payload = error.status_code, {"error": {"code": error.code}}
                elapsed = (time.monotonic() - started) * 1000
                result = (brief_observation(payload, case, fixture, profile, digest[1]) if status == 200
                          else rejected_observation(status, payload, case))
                rows.append({"family": "brief", "case": case.key, "mode": "brief", "repetition": repeat,
                             "elapsed_ms": elapsed, **result})
                await session.rollback()
        boundary = []
        if live:
            for path, body in (
                (f"/organizations/{fixture.foreign}/semantic-search", {"q": "Python", "mode": "semantic"}),
                (job_path(fixture, brief=True) + f"/candidates/{fixture.candidates['foreign']}/grounded-explanation", {"language": "en"}),
            ):
                status, _ = await client.call("POST", path, body)
                boundary.append(status == 404)
        else:
            for method, kwargs, code in (
                (semantic.search, {"organization_id": fixture.foreign, "user_id": fixture.user,
                                   "job_id": fixture.job}, "ORGANIZATION_NOT_FOUND"),
                (explanation.explain, fixture.scope(brief=True) | {"candidate_id": fixture.candidates["foreign"]}, "CANDIDATE_NOT_FOUND"),
            ):
                try:
                    await method(SemanticJobQuery() if method == semantic.search else ExplanationRequest(), **kwargs)
                except AppError as error:
                    boundary.append(error.status_code == 404 and error.code == code)
                else:
                    boundary.append(False)
    return evaluate(reference, rows, model_kind="live" if live else "fixture", embedding_digest=digest[0],
                    chat_digest=digest[1], tenant_boundary_ok=all(boundary) and len(boundary) == 2)


async def run(live=False):
    settings = get_settings().model_copy(update={"semantic_enabled": True, "explanations_enabled": True})
    project = os.environ.get("AGENTHIRE_QUALITY_PROJECT") if live else None
    if live and project is None:
        raise ValueError("quality_project_required")
    require_test_database(settings, project)
    reference = load_reference()
    fixture = QualityFixture(reference)
    encoder = LocalEmbeddingEncoder(settings.embedding_base_url) if live else FixtureEncoder()
    generator = LocalChatGenerator(settings.chat_base_url) if live else FixtureGenerator(reference)
    identity = await encoder.identity()
    # Check inventory before and after the run as well as each generated response.
    chat_digest = await asyncio.to_thread(generator._identity, time.monotonic() + 30) if live else "e" * 64
    try:
        await fixture.seed(async_session_factory, settings, encoder, identity)
        report = await collect(reference, fixture, async_session_factory, settings, encoder, generator,
                               (identity.digest, chat_digest), live=live)
        if await encoder.identity() != identity:
            raise ValueError("quality_embedding_model_changed")
        if live and await asyncio.to_thread(generator._identity, time.monotonic() + 30) != chat_digest:
            raise ValueError("quality_chat_model_changed")
        return report
    finally:
        try:
            await fixture.cleanup(async_session_factory)
        finally:
            await engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-model", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(run(args.live_model))
        print(json.dumps(report, ensure_ascii=True, sort_keys=True, allow_nan=False))
        return 0 if report["quality_passed" if args.live_model else "contract_passed"] else 1
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, AppError, SQLAlchemyError,
            ExplanationFailure, EmbeddingFailure):
        print(json.dumps({"status": "failed", "diagnostic": "quality_collection_incomplete"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
