import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.text_chunking import chunk_text
from app.db.base import Base
from app.models import (
    Candidate,
    CandidateDocument,
    DocumentChunk,
    DocumentChunkSet,
    DocumentExtraction,
    Organization,
    User,
)
from app.repositories.document_chunk import DocumentChunkRepository


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Organization.__table__,
            Candidate.__table__,
            CandidateDocument.__table__,
            DocumentExtraction.__table__,
            DocumentChunkSet.__table__,
            DocumentChunk.__table__,
        ],
    )
    user, org, candidate, document, chunk_set = [uuid4() for _ in range(5)]
    with engine.begin() as connection:
        connection.execute(
            insert(User),
            {"id": user, "email": "chunk@example.com", "password_hash": "hash"},
        )
        connection.execute(
            insert(Organization), {"id": org, "name": "Chunks", "slug": "chunks"}
        )
        connection.execute(
            insert(Candidate),
            {"id": candidate, "organization_id": org, "full_name": "Ada"},
        )
        connection.execute(
            insert(CandidateDocument),
            {
                "id": document,
                "organization_id": org,
                "candidate_id": candidate,
                "uploaded_by_user_id": user,
                "filename": "resume.pdf",
                "content_type": "application/pdf",
                "size_bytes": 50,
                "sha256": "a" * 64,
                "storage_key": uuid4().hex + ".pdf",
                "status": "ready",
            },
        )
        connection.execute(
            insert(DocumentExtraction),
            {
                "document_id": document,
                "status": "succeeded",
                "attempts": 1,
                "text": "abcdefgh",
                "page_count": 1,
                "completed_at": datetime.now(UTC),
            },
        )
    values = {
        "id": chunk_set,
        "document_id": document,
        "source_document_sha256": "a" * 64,
        "source_text_sha256": "b" * 64,
        "source_char_count": 8,
        "page_count": 1,
        "chunker_version": "char-window-v1",
        "chunk_max_chars": 4,
        "chunk_overlap_chars": 1,
        "chunk_count": 3,
    }
    yield engine, values
    engine.dispose()


def seed(connection, values):
    connection.execute(insert(DocumentChunkSet), values)
    for chunk in chunk_text("abcdefgh", max_chars=4, overlap_chars=1, max_count=3):
        connection.execute(
            insert(DocumentChunk),
            {
                "chunk_set_id": values["id"],
                "position": chunk.position,
                "start_offset": chunk.start_offset,
                "end_offset": chunk.end_offset,
                "text": chunk.text,
                "sha256": chunk.sha256,
            },
        )


@pytest.mark.parametrize(
    "parent", [CandidateDocument, DocumentExtraction], ids=["document", "extraction"]
)
def test_source_deletion_cascades_through_sets_and_chunks(database, parent) -> None:
    engine, values = database
    with engine.begin() as connection:
        seed(connection, values)
        column = parent.id if parent is CandidateDocument else parent.document_id
        connection.execute(
            parent.__table__.delete().where(column == values["document_id"])
        )
        for model in (DocumentChunkSet, DocumentChunk):
            assert (
                connection.execute(select(func.count()).select_from(model)).scalar_one()
                == 0
            )


def test_same_source_and_policy_are_unique_but_policy_versions_are_preserved(
    database,
) -> None:
    engine, values = database
    with engine.begin() as connection:
        connection.execute(insert(DocumentChunkSet), values)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert(DocumentChunkSet), values | {"id": uuid4()})
    with engine.begin() as connection:
        connection.execute(
            insert(DocumentChunkSet), values | {"id": uuid4(), "chunk_max_chars": 5}
        )
        connection.execute(
            insert(DocumentChunkSet),
            values | {"id": uuid4(), "chunker_version": "char-window-v2"},
        )
        assert (
            connection.execute(
                select(func.count()).select_from(DocumentChunkSet)
            ).scalar_one()
            == 3
        )


@pytest.mark.parametrize(
    "bad",
    [
        {"document_id": uuid4()},
        {"source_char_count": 0},
        {"page_count": 0},
        {"chunk_count": 0},
        {"chunk_max_chars": 0},
        {"chunk_overlap_chars": -1},
        {"chunk_overlap_chars": 4},
        {"source_text_sha256": "short"},
        {"source_document_sha256": "short"},
    ],
)
def test_invalid_set_metadata_is_rejected_by_database(database, bad: dict) -> None:
    engine, values = database
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert(DocumentChunkSet), values | bad)


@pytest.mark.parametrize(
    "bad",
    [
        {"chunk_set_id": uuid4()},
        {"position": -1},
        {"start_offset": -1},
        {"end_offset": 0},
        {"end_offset": 5},
        {"sha256": "short"},
    ],
)
def test_invalid_chunk_offsets_and_ownership_are_rejected(database, bad: dict) -> None:
    engine, values = database
    with engine.begin() as connection:
        connection.execute(insert(DocumentChunkSet), values)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert(DocumentChunk),
            {
                "chunk_set_id": values["id"],
                "position": 0,
                "start_offset": 0,
                "end_offset": 4,
                "text": "abcd",
                "sha256": "a" * 64,
            }
            | bad,
        )


@pytest.mark.parametrize(
    "bad",
    [
        {"position": 0, "start_offset": 1, "end_offset": 5},
        {"position": 1, "start_offset": 0, "end_offset": 4},
    ],
)
def test_positions_and_start_offsets_are_unique_per_set(database, bad: dict) -> None:
    engine, values = database
    with engine.begin() as connection:
        seed(connection, values)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert(DocumentChunk),
            {
                "chunk_set_id": values["id"],
                "text": "abcd",
                "sha256": "a" * 64,
            }
            | bad,
        )


def test_partial_generation_rolls_back_the_entire_set(database) -> None:
    engine, values = database
    with pytest.raises(IntegrityError), engine.begin() as connection:
        seed(connection, values)
        connection.execute(
            insert(DocumentChunk),
            {
                "chunk_set_id": values["id"],
                "position": 4,
                "start_offset": 9,
                "end_offset": 10,
                "text": "wrong length",
                "sha256": "a" * 64,
            },
        )
    with engine.begin() as connection:
        assert connection.execute(select(DocumentChunkSet)).all() == []
        assert connection.execute(select(DocumentChunk)).all() == []


def test_real_repository_queries_persist_page_scope_and_cascade(database) -> None:
    engine, values = database

    class Adapter:
        def __init__(self, session):
            self.session = session

        def add(self, value):
            self.session.add(value)

        async def flush(self):
            self.session.flush()

        async def refresh(self, value):
            self.session.refresh(value)

        async def execute(self, *args, **kwargs):
            return self.session.execute(*args, **kwargs)

    async def verify():
        with Session(engine, expire_on_commit=False) as session:
            document = session.execute(
                select(CandidateDocument).where(
                    CandidateDocument.id == values["document_id"]
                )
            ).scalar_one()
            scope = {
                "organization_id": document.organization_id,
                "candidate_id": document.candidate_id,
                "document_id": document.id,
            }
            repository = DocumentChunkRepository(Adapter(session))
            chunk_set = await repository.create(
                DocumentChunkSet(**values),
                chunk_text("abcdefgh", max_chars=4, overlap_chars=1, max_count=3),
            )
            session.commit()
            history, total = await repository.list_sets(**scope, limit=1, offset=0)
            assert total == 1 and history[0].id == chunk_set.id
            assert (
                await repository.get_policy(
                    **scope,
                    source_text_sha256=values["source_text_sha256"],
                    chunker_version="char-window-v1",
                    max_chars=4,
                    overlap_chars=1,
                )
                is chunk_set
            )
            chunks = await repository.list_chunks(
                **scope, chunk_set_id=chunk_set.id, limit=2, offset=1
            )
            assert [chunk.position for chunk in chunks] == [1, 2]
            outsider = scope | {"organization_id": uuid4()}
            assert await repository.get(**outsider, chunk_set_id=chunk_set.id) is None
            assert (
                await repository.list_chunks(
                    **outsider, chunk_set_id=chunk_set.id, limit=2, offset=0
                )
                == []
            )
            assert await repository.list_sets(**outsider, limit=2, offset=0) == ([], 0)
            session.execute(
                delete(CandidateDocument).where(CandidateDocument.id == document.id)
            )
            session.commit()
            assert await repository.get(**scope, chunk_set_id=chunk_set.id) is None

    asyncio.run(verify())
