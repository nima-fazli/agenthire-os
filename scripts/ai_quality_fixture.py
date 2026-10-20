"""Random-ID synthetic fixtures restricted to the test database and their own cleanup scope."""

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete

from app.core.local_chat import ChatResult
from app.core.semantic_embeddings import (
    DIMENSIONS,
    ENCODING_VERSION,
    MODEL_TAG,
    ModelIdentity,
)
from app.models import (
    Candidate,
    CandidateDocument,
    DocumentChunk,
    DocumentChunkSet,
    DocumentEmbedding,
    DocumentEmbeddingJob,
    DocumentExtraction,
    Job,
    Organization,
    OrganizationMembership,
    User,
)
from scripts.ci_plan import validate_project_name
from scripts.fixture_session import fixture_session


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def require_test_database(settings, project=None):
    if (settings.environment != "test" or settings.postgres_host != "postgres"
            or settings.postgres_db != "agenthire_ci" or settings.postgres_user != "agenthire_ci"):
        raise ValueError("quality_requires_isolated_test_database")
    if project is not None:
        validate_project_name(project)


class FixtureEncoder:
    async def identity(self):
        return ModelIdentity("f" * 64)

    async def encode(self, texts, identity):
        values = []
        for text in texts:
            vector = [0.0] * DIMENSIONS
            for word in re.findall(r"\w+", text.casefold()):
                index = int(hashlib.sha256(word.encode()).hexdigest()[:8], 16) % DIMENSIONS
                vector[index] += 1
            norm = math.hypot(*vector)
            values.append(tuple(v / norm for v in vector))
        return tuple(values)


class FixtureGenerator:
    def __init__(self, reference):
        self.anchors = {case.context: case.anchor for case in reference.briefs if case.anchor}

    async def generate(self, messages, schema):
        data = json.loads(messages[1]["content"])
        sources = {item["id"]: item["text"] for item in data["sources"]}
        quotes = [{"criterion": c["key"], "source": c["source"], "quote": self.anchors[sources[c["source"]]]}
                  for c in data["criteria"]]
        return ChatResult({"quotes": quotes}, "e" * 64, 100, 30)


@dataclass
class QualityFixture:
    reference: object
    user: object = field(default_factory=uuid4)
    org: object = field(default_factory=uuid4)
    brief_org: object = field(default_factory=uuid4)
    foreign: object = field(default_factory=uuid4)
    job: object = field(default_factory=uuid4)
    brief_job: object = field(default_factory=uuid4)
    candidates: dict = field(default_factory=dict)
    witnesses: dict = field(default_factory=dict)
    token: str = field(default="", repr=False)

    def scope(self, *, brief=False):
        return {"organization_id": self.brief_org if brief else self.org, "user_id": self.user,
                "job_id": self.brief_job if brief else self.job}

    async def seed(self, factory, settings, encoder, identity):
        entries = [(item.key, item.name, item.text, "", self.org, True) for item in self.reference.resumes]
        entries += [("foreign", "Excluded reference", self.reference.resumes[0].text, "", self.foreign, True)]
        entries += [(item.key, "Brief reference", item.context, item.prefix, self.brief_org, False)
                    for item in self.reference.briefs]
        vector_texts = tuple(text for _, _, text, _, _, embedded in entries if embedded)
        vectors = []
        for start in range(0, len(vector_texts), 4):
            vectors.extend(await encoder.encode(vector_texts[start:start + 4], identity))
        if len(vectors) != len(vector_texts):
            raise ValueError("quality_embedding_batch_incomplete")
        async with factory() as session:
            session.add(User(id=self.user, email=f"quality-{self.user.hex}@example.com", password_hash="synthetic"))
            session.add_all([Organization(id=org, name="Quality fixture", slug="quality-" + org.hex)
                             for org in (self.org, self.brief_org, self.foreign)])
            await session.flush()
            record, self.token = fixture_session(self.user, settings)
            session.add(record)
            session.add_all([OrganizationMembership(organization_id=org, user_id=self.user, role="owner")
                             for org in (self.org, self.brief_org)])
            session.add_all([Job(id=job, organization_id=org, title="Quality reference", description="Synthetic reference")
                             for job, org in ((self.job, self.org), (self.brief_job, self.brief_org))])
            for key, name, context, prefix, org, embedded in entries:
                candidate = self.candidates[key] = uuid4()
                session.add(Candidate(id=candidate, organization_id=org, full_name=name))
                await session.flush()
                if context is None:
                    continue
                document, chunk_set, embedding_job = uuid4(), uuid4(), uuid4()
                text = prefix + context
                parts = [prefix, context] if prefix else [context]
                witness = {"document_id": document, "chunk_set_id": chunk_set, "candidate_id": candidate,
                           "document_sha": sha("synthetic-document:" + document.hex), "text": text,
                           "parts": parts, "embedding_job_id": embedding_job if embedded else None}
                self.witnesses[key] = witness
                session.add(CandidateDocument(id=document, organization_id=org, candidate_id=candidate,
                    uploaded_by_user_id=self.user, filename="synthetic.pdf", content_type="application/pdf", size_bytes=100,
                    sha256=witness["document_sha"], storage_key=document.hex + ".pdf", status="ready"))
                await session.flush()
                session.add(DocumentExtraction(document_id=document, status="succeeded", attempts=1, text=text,
                    page_count=1, completed_at=datetime.now(UTC)))
                await session.flush()
                session.add(DocumentChunkSet(id=chunk_set, document_id=document,
                    source_document_sha256=witness["document_sha"], source_text_sha256=sha(text),
                    source_char_count=len(text), page_count=1, chunker_version="quality-text-seed-v1",
                    chunk_max_chars=4000, chunk_overlap_chars=0, chunk_count=len(parts)))
                await session.flush()
                offset = 0
                for position, part in enumerate(parts):
                    session.add(DocumentChunk(chunk_set_id=chunk_set, position=position, start_offset=offset,
                        end_offset=offset + len(part), text=part, sha256=sha(part)))
                    offset += len(part)
                if embedded:
                    session.add(DocumentEmbeddingJob(id=embedding_job, chunk_set_id=chunk_set, model_tag=MODEL_TAG,
                        model_digest=identity.digest, encoding_version=ENCODING_VERSION, source_text_sha256=sha(text),
                        chunk_count=1, status="succeeded", attempts=1, completed_at=datetime.now(UTC)))
                    await session.flush()
                    session.add(DocumentEmbedding(job_id=embedding_job, chunk_set_id=chunk_set, position=0,
                        chunk_sha256=sha(text), embedding=vectors.pop(0)))
                await session.flush()
            await session.commit()

    async def cleanup(self, factory):
        async with factory() as session:
            for model, condition in (
                (CandidateDocument, CandidateDocument.id.in_([w["document_id"] for w in self.witnesses.values()])),
                (Candidate, Candidate.id.in_(list(self.candidates.values()))),
                (Job, Job.id.in_([self.job, self.brief_job])),
                (OrganizationMembership, OrganizationMembership.organization_id.in_([self.org, self.brief_org])),
                (Organization, Organization.id.in_([self.org, self.brief_org, self.foreign])),
                (User, User.id == self.user),
            ):
                await session.execute(delete(model).where(condition))
            await session.commit()


def verify_source(value, witness, *, citation=False):
    """Verify offsets and all source hashes without using production grounding helpers."""
    position = value.chunk_position
    if not 0 <= position < len(witness["parts"]):
        return False
    part = witness["parts"][position]
    start = sum(len(text) for text in witness["parts"][:position])
    return (value.document_id == witness["document_id"] and value.chunk_set_id == witness["chunk_set_id"]
            and value.start_offset == start and value.end_offset == start + len(part)
            and witness["text"][start:value.end_offset] == part
            and (value.quote if citation else value.text) == part
            and value.chunk_sha256 == sha(part) and value.source_text_sha256 == sha(witness["text"])
            and value.source_document_sha256 == witness["document_sha"]
            and (not citation or value.quote_sha256 == sha(part)))
