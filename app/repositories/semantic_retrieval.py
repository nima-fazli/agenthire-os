from sqlalchemy import (
    Float,
    and_,
    exists,
    func,
    literal,
    literal_column,
    select,
    true,
    union_all,
)
from sqlalchemy.orm import aliased

from app.core.semantic_embeddings import (
    DIMENSIONS,
    ENCODING_VERSION,
    MODEL_TAG,
    EmbeddingVector,
)
from app.core.semantic_retrieval import EVIDENCE_FIELDS, WINDOW
from app.core.text_search import search_query, search_vector
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.document_chunk import DocumentChunk, DocumentChunkSet
from app.models.document_embeddings import DocumentEmbedding, DocumentEmbeddingJob
from app.models.document_extraction import DocumentExtraction
from app.models.job import Job
from app.models.job_search_profile import JobSearchProfile
from app.models.organization_membership import OrganizationMembership


class SemanticRetrievalRepository:
    def __init__(self, session):
        self._session = session

    @staticmethod
    def statement(*, organization_id, user_id, data, q, vector, identity,
                  job_id=None, profile=None):
        member = exists(select(OrganizationMembership.id).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
        ))
        job_exists = literal(True) if job_id is None else exists(select(Job.id).where(
            Job.id == job_id, Job.organization_id == organization_id,
        ))
        profile_current = literal(True) if job_id is None else exists(select(JobSearchProfile.job_id).where(
            JobSearchProfile.job_id == job_id, JobSearchProfile.query_text == q,
            JobSearchProfile.revision == profile["revision"],
            JobSearchProfile.updated_at == profile["updated_at"],
        ))
        latest = aliased(DocumentChunkSet)
        latest_id = (select(latest.id).where(latest.document_id == CandidateDocument.id)
                     .order_by(latest.created_at.desc(), latest.id.desc()).limit(1)
                     .correlate(CandidateDocument).scalar_subquery())
        complete = (select(DocumentEmbedding.job_id, func.count().label("count"))
                    .group_by(DocumentEmbedding.job_id).subquery())
        job_source = and_(
            DocumentEmbeddingJob.chunk_set_id == DocumentChunkSet.id,
            DocumentEmbeddingJob.status == "succeeded",
            DocumentEmbeddingJob.model_tag == MODEL_TAG,
            DocumentEmbeddingJob.model_digest == identity.digest,
            DocumentEmbeddingJob.encoding_version == ENCODING_VERSION,
            DocumentEmbeddingJob.source_text_sha256 == DocumentChunkSet.source_text_sha256,
            DocumentEmbeddingJob.chunk_count == DocumentChunkSet.chunk_count,
            exists(select(complete.c.job_id).where(
                complete.c.job_id == DocumentEmbeddingJob.id,
                complete.c.count == DocumentChunkSet.chunk_count,
            )),
        )

        def digest(column):
            return func.encode(func.sha256(func.convert_to(column, literal_column("'UTF8'"))),
                               literal_column("'hex'"))

        source = (select(
            CandidateDocument.id.label("document_id"), CandidateDocument.candidate_id,
            Candidate.full_name.label("candidate_name"), CandidateDocument.filename,
            DocumentChunk.chunk_set_id, DocumentChunk.position.label("chunk_position"),
            DocumentChunk.start_offset, DocumentChunk.end_offset, DocumentChunk.text,
            DocumentChunk.sha256.label("chunk_sha256"),
            DocumentChunkSet.source_document_sha256, DocumentChunkSet.source_text_sha256,
            DocumentEmbeddingJob.id.label("embedding_job_id"), DocumentEmbedding.embedding.label("vector"),
        ).select_from(DocumentChunk).join(DocumentChunkSet)
            .join(DocumentExtraction, DocumentExtraction.document_id == DocumentChunkSet.document_id)
            .join(CandidateDocument, CandidateDocument.id == DocumentChunkSet.document_id)
            .join(Candidate, and_(Candidate.id == CandidateDocument.candidate_id,
                                 Candidate.organization_id == organization_id))
            .outerjoin(DocumentEmbeddingJob, job_source)
            .outerjoin(DocumentEmbedding, and_(DocumentEmbedding.job_id == DocumentEmbeddingJob.id,
                DocumentEmbedding.chunk_set_id == DocumentChunk.chunk_set_id,
                DocumentEmbedding.position == DocumentChunk.position,
                DocumentEmbedding.chunk_sha256 == DocumentChunk.sha256))
            .where(member, job_exists, profile_current,
                CandidateDocument.organization_id == organization_id,
                CandidateDocument.status == "ready", DocumentExtraction.status == "succeeded",
                DocumentChunkSet.id == latest_id,
                DocumentChunkSet.source_document_sha256 == CandidateDocument.sha256,
                DocumentChunkSet.source_text_sha256 == digest(DocumentExtraction.text),
                DocumentChunkSet.source_char_count == func.length(DocumentExtraction.text),
                DocumentChunk.position < DocumentChunkSet.chunk_count,
                DocumentChunk.end_offset <= DocumentChunkSet.source_char_count,
                DocumentChunk.text == func.substr(DocumentExtraction.text, DocumentChunk.start_offset + 1,
                                                 DocumentChunk.end_offset - DocumentChunk.start_offset),
                DocumentChunk.sha256 == digest(DocumentChunk.text)))
        if job_id is None:
            if data.candidate_id is not None:
                source = source.where(CandidateDocument.candidate_id == data.candidate_id)
            if data.document_id is not None:
                source = source.where(CandidateDocument.id == data.document_id)
        elif data.applicants_only:
            source = source.where(exists(select(Application.id).where(
                Application.organization_id == organization_id, Application.job_id == job_id,
                Application.candidate_id == CandidateDocument.candidate_id,
            )))
        source = source.cte("semantic_sources")
        cosine = func.greatest(-1.0, func.least(1.0, 1.0 - source.c.vector.op(
            "<=>", return_type=Float)(literal(vector, type_=EmbeddingVector(DIMENSIONS)))))
        text_vector, text_query = search_vector(source.c.text), search_query(q)
        lexical = func.ts_rank_cd(text_vector, text_query, 32)
        tie = (source.c.candidate_id, source.c.document_id, source.c.chunk_set_id, source.c.chunk_position)
        partition = source.c.candidate_id if job_id is not None else (
            source.c.document_id, source.c.chunk_set_id, source.c.chunk_position)

        def branch(name, score, condition):
            fields = [literal(None, type_=source.c.embedding_job_id.type).label(key) if name == "lexical" and key == "embedding_job_id"
                      else source.c[key] for key in EVIDENCE_FIELDS if key != "score"]
            ranked = select(*fields, score.label("score"), literal(name).label("branch"),
                func.row_number().over(partition_by=partition, order_by=(score.desc(), *tie))
                .label("witness")).where(condition).cte(name + "_ranked")
            best = select(ranked).where(ranked.c.witness == 1).cte(name + "_best")
            page = select(*[best.c[key] for key in (*EVIDENCE_FIELDS, "branch")])
            return best, page.order_by(best.c.score.desc(), *[best.c[c.key] for c in tie]).limit(WINDOW)

        semantic_all, semantic_page = branch("semantic", cosine,
                                             and_(source.c.vector.is_not(None), cosine >= data.min_similarity))
        lexical_all, lexical_page = branch("lexical", lexical,
            and_(literal(data.mode == "hybrid"), text_vector.bool_op("@@")(text_query)))
        windows = union_all(semantic_page, lexical_page).cte("retrieval_windows")
        summary = select(
            member.label("authorized"), job_exists.label("job_exists"),
            profile_current.label("profile_current"),
            select(func.count()).select_from(source).scalar_subquery().label("eligible_chunks"),
            select(func.count()).select_from(source).where(source.c.vector.is_not(None))
            .scalar_subquery().label("embedded_chunks"),
            ((select(func.count()).select_from(semantic_all).scalar_subquery() > WINDOW) |
             (select(func.count()).select_from(lexical_all).scalar_subquery() > WINDOW)).label("pool_truncated"),
        ).cte("retrieval_summary")
        return (select(summary, windows).select_from(summary.outerjoin(windows, true()))
                .order_by(windows.c.branch, windows.c.score.desc(), windows.c.candidate_id,
                          windows.c.document_id, windows.c.chunk_set_id, windows.c.chunk_position))

    async def search(self, *, timeout_ms, **kwargs):
        await self._session.execute(select(func.set_config("statement_timeout", f"{timeout_ms}ms", True)))
        rows = (await self._session.execute(self.statement(**kwargs))).mappings().all()
        keys = ("authorized", "job_exists", "profile_current", "eligible_chunks", "embedded_chunks", "pool_truncated")
        return {key: rows[0][key] for key in keys} | {
            "rows": [{key: value for key, value in row.items() if key not in keys}
                     for row in rows if row["branch"] is not None]
        }
