import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.models import Candidate, CandidateDocument, Organization, User
from app.repositories.candidate_document import CandidateDocumentRepository
from app.schemas.candidate_document import DocumentUpload


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
        ],
    )
    user, first, second, candidate, other = [uuid4() for _ in range(5)]
    with engine.begin() as connection:
        connection.execute(
            insert(User),
            {"id": user, "email": "owner@example.com", "password_hash": "hash"},
        )
        connection.execute(
            insert(Organization),
            [
                {"id": first, "name": "First", "slug": "first"},
                {"id": second, "name": "Second", "slug": "second"},
            ],
        )
        connection.execute(
            insert(Candidate),
            [
                {"id": candidate, "organization_id": first, "full_name": "Ada"},
                {"id": other, "organization_id": second, "full_name": "Grace"},
            ],
        )
    values = {
        "id": uuid4(),
        "organization_id": first,
        "candidate_id": candidate,
        "uploaded_by_user_id": user,
        "filename": "resume.pdf",
        "content_type": "application/pdf",
        "size_bytes": 50,
        "sha256": "a" * 64,
        "storage_key": uuid4().hex + ".pdf",
        "status": "ready",
    }
    yield engine, values, second, other
    engine.dispose()


def test_database_blocks_cross_tenant_candidate_reference(database) -> None:
    engine, values, second, _ = database
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            insert(CandidateDocument), values | {"organization_id": second}
        )


@pytest.mark.parametrize(
    "change",
    [
        {"size_bytes": 0},
        {"sha256": "short"},
        {"status": "public"},
        {"content_type": "text/html"},
        {"uploaded_by_user_id": uuid4()},
    ],
)
def test_database_rejects_invalid_document_metadata(database, change: dict) -> None:
    engine, values, _, _ = database
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(insert(CandidateDocument), values | change)


def test_digest_is_unique_per_candidate_and_can_be_reused_after_deletion(
    database,
) -> None:
    engine, values, second, other = database
    with engine.begin() as connection:
        connection.execute(insert(CandidateDocument), values)
    duplicate = values | {"id": uuid4(), "storage_key": uuid4().hex + ".pdf"}
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(insert(CandidateDocument), duplicate)
    with engine.begin() as connection:
        connection.execute(
            insert(CandidateDocument),
            duplicate | {"organization_id": second, "candidate_id": other},
        )
        connection.execute(
            CandidateDocument.__table__.delete().where(
                CandidateDocument.id == values["id"]
            )
        )
        connection.execute(insert(CandidateDocument), values | {"id": uuid4()})


@pytest.mark.parametrize(
    "filename", ["../resume.pdf", "folder\\resume.pdf", "resume.txt", "x\n.pdf", ".pdf"]
)
def test_upload_filename_rejects_paths_and_invalid_types(filename: str) -> None:
    with pytest.raises(ValidationError):
        DocumentUpload(filename=filename)


def test_upload_filename_supports_unicode_and_rejects_extra_fields() -> None:
    assert DocumentUpload(filename=" رزومه.PDF ").filename == "رزومه.PDF"
    with pytest.raises(ValidationError):
        DocumentUpload(filename="resume.pdf", storage_key="untrusted")


@pytest.mark.parametrize("operation", ["get", "digest", "list", "delete"])
def test_repository_queries_are_scoped_and_never_commit(operation: str) -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = []
    session.commit = AsyncMock()
    scope = {"organization_id": uuid4(), "candidate_id": uuid4()}
    repository = CandidateDocumentRepository(session)
    if operation == "get":
        asyncio.run(
            repository.get_for_candidate(**scope, document_id=uuid4(), for_update=True)
        )
    elif operation == "digest":
        asyncio.run(repository.get_by_digest(**scope, sha256="a" * 64))
    elif operation == "list":
        asyncio.run(repository.list_for_candidate(**scope, limit=10, offset=20))
    else:
        asyncio.run(repository.delete_for_candidate(**scope, document_id=uuid4()))
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "candidate_documents.organization_id =" in sql
    assert "candidate_documents.candidate_id =" in sql
    assert all(value in statement.compile().params.values() for value in scope.values())
    if operation == "get":
        assert "FOR UPDATE" in sql
        assert statement.get_execution_options()["populate_existing"] is True
    if operation == "list":
        assert "ORDER BY" in sql and "LIMIT" in sql and "OFFSET" in sql
    session.commit.assert_not_awaited()


def test_repository_create_and_mark_deleting_only_flush() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    repository = CandidateDocumentRepository(session)
    document = asyncio.run(
        repository.create(
            organization_id=uuid4(),
            candidate_id=uuid4(),
            uploaded_by_user_id=uuid4(),
            filename="resume.pdf",
            content_type="application/pdf",
            size_bytes=50,
            sha256="a" * 64,
            storage_key=uuid4().hex + ".pdf",
            status="ready",
        )
    )
    asyncio.run(repository.mark_deleting(document))
    assert document.status == "deleting"
    session.add.assert_called_once_with(document)
    session.refresh.assert_awaited_once_with(document)
    assert session.flush.await_count == 2
    session.commit.assert_not_awaited()
