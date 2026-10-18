import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.api.routes.recruiting import get_recruiting_service
from app.core.errors import AppError, ConflictError, NotFoundError
from app.main import app
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.repositories.recruiting import (
    RecruitingRepository,
    literal_pattern,
    page_statement,
)
from app.schemas.recruiting import CandidateEdit, JobEdit, PageOptions
from app.services.recruiting import RecruitingService

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("options", [
    {"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 10001},
    {"q": "x" * 121}, {"q": "a\x00b"}, {"unexpected": True},
])
def test_page_options_reject_invalid_bounds(options):
    with pytest.raises(ValidationError):
        PageOptions(**options)


def test_full_record_edits_clear_optional_fields_but_require_a_version():
    value = CandidateEdit(full_name=" Ada ", email=None, expected_updated_at=NOW)
    assert value.full_name == "Ada" and value.email is None
    for body in ({"full_name": "Ada"}, {"full_name": None, "expected_updated_at": NOW},
                 {"full_name": "Ada", "expected_updated_at": NOW.replace(tzinfo=None)},
                 {"full_name": "Ada", "expected_updated_at": NOW, "organization_id": uuid4()}):
        with pytest.raises(ValidationError):
            CandidateEdit(**body)
    with pytest.raises(ValidationError):
        JobEdit(title=" ", description="Fixture", expected_updated_at=NOW)


@pytest.fixture
def database():
    engine = create_engine("sqlite://")
    tables = [User.__table__, Organization.__table__, OrganizationMembership.__table__,
              Job.__table__, Candidate.__table__, Application.__table__]
    User.metadata.create_all(engine, tables=tables)
    user, other, org, foreign = (uuid4() for _ in range(4))
    with engine.begin() as connection:
        connection.execute(User.__table__.insert(), [
            {"id": user, "email": "one@example.com", "password_hash": "fixture"},
            {"id": other, "email": "two@example.com", "password_hash": "fixture"},
        ])
        connection.execute(Organization.__table__.insert(), [
            {"id": org, "name": "Alpha", "slug": "alpha"},
            {"id": foreign, "name": "Private", "slug": "private"},
        ])
        connection.execute(OrganizationMembership.__table__.insert(), [
            {"organization_id": org, "user_id": user},
            {"organization_id": foreign, "user_id": other},
        ])
        jobs = [{"id": uuid4(), "organization_id": org, "title": f"Engineer {i}",
                 "description": "Synthetic", "status": "open", "created_at": NOW}
                for i in range(23)]
        jobs += [{"id": uuid4(), "organization_id": foreign, "title": "Private",
                  "description": "PRIVATE_TEXT", "status": "open", "created_at": NOW}]
        connection.execute(Job.__table__.insert(), jobs)
        candidates = [{"id": uuid4(), "organization_id": org, "full_name": f"Candidate {i}",
                       "headline": "A_100%" if i == 0 else "Python", "created_at": NOW}
                      for i in range(24)]
        candidates += [{"id": uuid4(), "organization_id": foreign, "full_name": "Private",
                        "headline": "PRIVATE_TEXT", "created_at": NOW}]
        connection.execute(Candidate.__table__.insert(), candidates)
        connection.execute(Application.__table__.insert(), [
            {"organization_id": org, "job_id": jobs[0]["id"], "candidate_id": item["id"],
             "status": "screening" if i == 0 else "applied"}
            for i, item in enumerate(candidates[:-1])
        ])
        class Session:
            async def execute(self, statement):
                return connection.execute(statement)
        yield SimpleNamespace(repository=RecruitingRepository(Session()), user=user, other=other,
                              org=org, foreign=foreign, jobs=jobs, candidates=candidates)
    engine.dispose()


def read_page(database, kind, **options):
    filters = options.pop("filters", {})
    return asyncio.run(database.repository.page(kind, PageOptions(**options), user_id=database.user,
                       organization_id=database.org, **filters))


def test_real_queries_paginate_ties_and_preserve_empty_page_totals(database):
    first = read_page(database, "jobs")
    second = read_page(database, "jobs", offset=20)
    assert first["total"] == second["total"] == 23
    assert len(first["items"]) == 20 and len(second["items"]) == 3
    ids = [row["id"] for row in first["items"] + second["items"]]
    assert len(set(ids)) == 23 and ids == sorted(ids, reverse=True)
    empty = read_page(database, "jobs", offset=100)
    assert empty["items"] == [] and empty["total"] == 23
    assert all(row["organization_id"] == database.org for row in first["items"])


def test_search_uses_literal_wildcards_and_real_server_filters(database):
    assert literal_pattern("a_%\\") == "%a\\_\\%\\\\%"
    page = read_page(database, "candidates", q="A_100%")
    assert page["total"] == 1 and page["items"][0]["headline"] == "A_100%"
    assert read_page(database, "jobs", q="engineer")["total"] == 23
    assert read_page(database, "candidates", q="PRIVATE_TEXT")["total"] == 0
    assert read_page(database, "jobs", filters={"status": "closed"})["total"] == 0


def test_organization_membership_and_application_filters_execute_in_database(database):
    organizations = read_page(database, "organizations")
    assert organizations["total"] == 1 and organizations["items"][0]["id"] == database.org
    page = read_page(database, "applications", filters={"status": "screening", "job_id": database.jobs[0]["id"]})
    assert page["total"] == 1
    row = page["items"][0]
    assert row["candidate_name"] == "Candidate 0" and row["job_title"] == "Engineer 0"
    assert read_page(database, "applications", filters={"candidate_id": uuid4()})["total"] == 0


def test_postgresql_query_keeps_user_input_in_parameters():
    query = page_statement("candidates", PageOptions(q="%' OR 1=1 --"),
                           user_id=uuid4(), organization_id=uuid4())
    compiled = query.compile(dialect=postgresql.dialect())
    assert "OR 1=1" not in str(compiled)
    assert "LEFT OUTER JOIN" in str(compiled) and "created_at DESC" in str(compiled)
    assert any("OR 1=1" in str(value) for value in compiled.params.values())


def service_fixture():
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=MagicMock())
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    service = RecruitingService(session)
    service.organizations.get_for_user = AsyncMock()
    service.repository.page = AsyncMock()
    return service, session


def test_denied_membership_never_reaches_page_data():
    service, session = service_fixture()
    service.organizations.get_for_user.side_effect = NotFoundError(code="ORGANIZATION_NOT_FOUND", message="Missing")
    with pytest.raises(NotFoundError):
        asyncio.run(service.page("jobs", PageOptions(), user_id=uuid4(), organization_id=uuid4()))
    service.repository.page.assert_not_awaited()
    assert "statement_timeout" in str(session.execute.await_args.args[0])


def test_query_timeout_rolls_back_and_hides_raw_database_details():
    service, session = service_fixture()
    class Timeout(Exception):
        sqlstate = "57014"
    session.execute.side_effect = DBAPIError("PRIVATE_SQL", {}, Timeout("PRIVATE_TEXT"))
    with pytest.raises(AppError) as error:
        asyncio.run(service.page("jobs", PageOptions(), user_id=uuid4(), organization_id=uuid4()))
    assert error.value.code == "PAGE_QUERY_TIMEOUT" and "PRIVATE" not in str(error.value)
    session.rollback.assert_awaited_once()


@pytest.mark.parametrize("status,expected", [
    ("applied", ["rejected", "screening"]), ("screening", ["interview", "rejected"]),
    ("interview", ["offer", "rejected"]), ("offer", ["hired", "rejected"]),
    ("hired", []), ("rejected", []),
])
def test_application_choices_follow_existing_server_state_machine(status, expected):
    service, _ = service_fixture()
    service.repository.page.return_value = {"items": [{"status": status}]}
    page = asyncio.run(service.page("applications", PageOptions(), user_id=uuid4(), organization_id=uuid4()))
    assert page["items"][0]["allowed_statuses"] == expected


@pytest.mark.parametrize("kind", ["jobs", "candidates"])
def test_edits_lock_the_scoped_record_and_reject_a_stale_version(kind):
    service, session = service_fixture()
    record = Job(id=uuid4(), organization_id=uuid4(), updated_at=NOW, title="Original") if kind == "jobs" else Candidate(
        id=uuid4(), organization_id=uuid4(), updated_at=NOW, full_name="Original", email="old@example.com")
    session.execute.return_value.scalar_one_or_none.return_value = record
    data = JobEdit(title="Updated", description="Fixture", expected_updated_at=NOW - timedelta(seconds=1)) if kind == "jobs" else CandidateEdit(
        full_name="Updated", expected_updated_at=NOW - timedelta(seconds=1))
    with pytest.raises(ConflictError) as error:
        asyncio.run(service.edit(kind, record.id, data, organization_id=record.organization_id, user_id=uuid4()))
    assert error.value.code == "RECORD_CHANGED"
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
    query = session.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    assert "FOR UPDATE" in str(query) and record.organization_id in query.params.values()
    assert getattr(record, "title" if kind == "jobs" else "full_name") == "Original"


def test_successful_candidate_edit_clears_optional_fields_atomically():
    service, session = service_fixture()
    record = Candidate(id=uuid4(), organization_id=uuid4(), full_name="Old", email="old@example.com", updated_at=NOW)
    session.execute.return_value.scalar_one_or_none.return_value = record
    data = CandidateEdit(full_name="New", email=None, expected_updated_at=NOW)
    assert asyncio.run(service.edit("candidates", record.id, data, organization_id=record.organization_id, user_id=uuid4())) is record
    assert record.full_name == "New" and record.email is None
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


def test_busy_record_fails_without_waiting_or_retrying_a_write():
    service, session = service_fixture()
    class Busy(Exception):
        sqlstate = "55P03"
    session.execute.side_effect = DBAPIError("PRIVATE_SQL", {}, Busy())
    with pytest.raises(AppError) as error:
        asyncio.run(service.edit("jobs", uuid4(), JobEdit(
            title="Fixture", description="Fixture", expected_updated_at=NOW),
            organization_id=uuid4(), user_id=uuid4()))
    assert error.value.code == "RECORD_BUSY" and error.value.status_code == 503
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.fixture
def api():
    user = User(id=uuid4(), email="fixture@example.com", password_hash="fixture", is_active=True)
    service = AsyncMock(spec=RecruitingService)
    saved = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_recruiting_service] = lambda: service
    yield TestClient(app), service, user
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


@pytest.mark.parametrize("suffix", ["jobs", "candidates", "applications"])
def test_page_api_validates_queries_and_preserves_scope(api, suffix):
    client, service, user = api
    org = uuid4()
    service.page.return_value = {"items": [], "total": 0, "limit": 20, "offset": 40}
    path = f"/organizations/{org}/recruiting/{suffix}"
    response = client.get(path, params={"q": " Ada ", "offset": 40})
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    call = service.page.await_args
    assert call.args[0] == suffix and call.args[1].q == "Ada"
    assert call.kwargs["organization_id"] == org and call.kwargs["user_id"] == user.id
    for invalid in ({"limit": 101}, {"q": "\x00"}, {"offset": -1}):
        assert client.get(path, params=invalid).status_code == 422


def test_static_organization_page_precedes_dynamic_uuid_route(api):
    client, service, user = api
    service.page.return_value = {"items": [], "total": 0, "limit": 20, "offset": 0}
    assert client.get("/organizations/page").status_code == 200
    assert service.page.await_args.args[0] == "organizations"
    assert service.page.await_args.kwargs == {"user_id": user.id}


def test_edit_api_preserves_nulls_and_reports_concurrent_change(api):
    client, service, _ = api
    service.edit.side_effect = ConflictError(code="RECORD_CHANGED", message="Refresh")
    response = client.put(f"/organizations/{uuid4()}/recruiting/candidates/{uuid4()}", json={
        "full_name": "Ada", "email": None, "expected_updated_at": NOW.isoformat(),
    })
    assert response.status_code == 409 and response.json()["error"]["code"] == "RECORD_CHANGED"
    assert service.edit.await_args.args[2].email is None


def test_page_routes_require_authentication():
    assert TestClient(app).get("/organizations/page").status_code == 401
