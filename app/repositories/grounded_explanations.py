from sqlalchemy import and_, exists, func, literal, literal_column, select
from sqlalchemy.orm import aliased

from app.core.text_search import search_query, search_vector
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.document_chunk import DocumentChunk, DocumentChunkSet
from app.models.document_extraction import DocumentExtraction
from app.models.job import Job
from app.models.job_matching import JobMatchCriterion, JobMatchProfile
from app.models.organization_membership import OrganizationMembership


class GroundedExplanationRepository:
    def __init__(self, session):
        self._session = session

    @staticmethod
    def statement(snapshot, citations, *, organization_id, user_id):
        member = exists(select(OrganizationMembership.id).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id))
        job = exists(select(Job.id).where(Job.id == snapshot.job_id, Job.organization_id == organization_id))
        candidate = exists(select(Candidate.id).where(Candidate.id == snapshot.candidate_id,
                                                      Candidate.organization_id == organization_id))
        criteria = [exists(select(JobMatchCriterion.job_id).where(
            JobMatchCriterion.job_id == snapshot.job_id, JobMatchCriterion.position == item.position,
            JobMatchCriterion.key == item.key, JobMatchCriterion.label == item.label,
            JobMatchCriterion.query_text == item.q, JobMatchCriterion.importance == item.importance))
            for item in snapshot.criteria]
        count = select(func.count()).select_from(JobMatchCriterion).where(
            JobMatchCriterion.job_id == snapshot.job_id).scalar_subquery()
        profile = and_(exists(select(JobMatchProfile.job_id).where(
            JobMatchProfile.job_id == snapshot.job_id, JobMatchProfile.revision == snapshot.profile_revision,
            JobMatchProfile.updated_at == snapshot.profile_updated_at)), count == len(criteria), *criteria)
        latest = aliased(DocumentChunkSet)
        latest_id = (select(latest.id).where(latest.document_id == CandidateDocument.id)
                     .order_by(latest.created_at.desc(), latest.id.desc()).limit(1)
                     .correlate(CandidateDocument).scalar_subquery())

        def digest(column):
            return func.encode(func.sha256(func.convert_to(column, literal_column("'UTF8'"))),
                               literal_column("'hex'"))

        sources, quotes = [], []
        for item in snapshot.criteria:
            evidence = item.evidence
            if evidence is None:
                continue
            source = (select(DocumentChunk.chunk_set_id).select_from(DocumentChunk)
                .join(DocumentChunkSet).join(CandidateDocument, CandidateDocument.id == DocumentChunkSet.document_id)
                .join(DocumentExtraction, DocumentExtraction.document_id == CandidateDocument.id)
                .where(CandidateDocument.id == evidence.document_id,
                    CandidateDocument.organization_id == organization_id,
                    CandidateDocument.candidate_id == snapshot.candidate_id, CandidateDocument.status == "ready",
                    CandidateDocument.sha256 == evidence.source_document_sha256,
                    DocumentExtraction.status == "succeeded",
                    DocumentChunkSet.id == evidence.chunk_set_id, DocumentChunkSet.id == latest_id,
                    DocumentChunkSet.source_document_sha256 == CandidateDocument.sha256,
                    DocumentChunkSet.source_text_sha256 == evidence.source_text_sha256,
                    digest(DocumentExtraction.text) == evidence.source_text_sha256,
                    DocumentChunkSet.source_char_count == func.length(DocumentExtraction.text),
                    DocumentChunk.position == evidence.chunk_position,
                    DocumentChunk.position < DocumentChunkSet.chunk_count,
                    DocumentChunk.start_offset == evidence.start_offset,
                    DocumentChunk.end_offset == evidence.end_offset,
                    DocumentChunk.end_offset <= DocumentChunkSet.source_char_count,
                    DocumentChunk.sha256 == evidence.chunk_sha256, digest(DocumentChunk.text) == evidence.chunk_sha256,
                    DocumentChunk.text == evidence.text,
                    DocumentChunk.text == func.substr(DocumentExtraction.text, DocumentChunk.start_offset + 1,
                                                      DocumentChunk.end_offset - DocumentChunk.start_offset)))
            sources.append(exists(source))
            if item.key in citations:
                citation = citations[item.key]
                quotes.append(exists(source.where(
                    search_vector(literal(citation.quote)).bool_op("@@")(search_query(item.q)))))
        return select(member.label("authorized"), job.label("job_exists"), candidate.label("candidate_exists"),
                      profile.label("profile_current"), and_(True, *sources).label("sources_current"),
                      and_(True, *quotes).label("quotes_match"), func.statement_timestamp().label("validated_at"))

    async def check(self, snapshot, citations, *, timeout_ms, **scope):
        await self._session.execute(select(func.set_config("statement_timeout", f"{timeout_ms}ms", True)))
        return dict((await self._session.execute(self.statement(snapshot, citations, **scope))).mappings().one())
