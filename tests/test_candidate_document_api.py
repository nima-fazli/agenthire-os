import asyncio
import io
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from app.api.dependencies import get_current_user
from app.api.routes.candidate_documents import (
    DocumentContentResponse,
    get_candidate_document_service,
)
from app.core.errors import AppError
from app.main import app
from app.models.candidate_document import CandidateDocument
from app.models.user import User
from app.services.candidate_document import CandidateDocumentService

PDF = b"%PDF-1.7\nresume\n%%EOF\n"


@pytest.fixture
def context():
    user = User(
        id=uuid4(), email="owner@example.com", password_hash="hash", is_active=True
    )
    now = datetime.now(UTC)
    document = CandidateDocument(
        id=uuid4(),
        organization_id=uuid4(),
        candidate_id=uuid4(),
        uploaded_by_user_id=user.id,
        filename="رزومه.pdf",
        content_type="application/pdf",
        size_bytes=len(PDF),
        sha256="a" * 64,
        storage_key=uuid4().hex + ".pdf",
        status="ready",
        created_at=now,
        updated_at=now,
    )
    service = AsyncMock(spec=CandidateDocumentService)
    service.upload.return_value = document
    service.get_for_user.return_value = document
    service.list_for_user.return_value = [document]
    service.download_for_user.return_value = document, io.BytesIO(PDF)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_candidate_document_service] = lambda: service
    path = f"/organizations/{document.organization_id}/candidates/{document.candidate_id}/documents"
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client, service=service, user=user, document=document, path=path
        )
    app.dependency_overrides.clear()


def test_upload_accepts_binary_body_and_hides_storage_key(context) -> None:
    response = context.client.post(
        context.path,
        params={"filename": " رزومه.pdf "},
        content=PDF,
        headers={"Content-Type": "application/pdf"},
    )
    assert response.status_code == 201
    assert response.json()["filename"] == "رزومه.pdf"
    assert "storage_key" not in response.json()
    call = context.service.upload.await_args
    assert call.args[0].filename == "رزومه.pdf"
    assert call.kwargs["user_id"] == context.user.id
    assert call.kwargs["content_length"] == str(len(PDF))


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"filename": "../resume.pdf"},
        {"filename": "resume.docx"},
        {"filename": "resume.pdf", "storage_key": "untrusted"},
    ],
)
def test_upload_rejects_invalid_query_before_service(context, query: dict) -> None:
    response = context.client.post(context.path, params=query, content=PDF)
    assert response.status_code == 422
    context.service.upload.assert_not_awaited()


def test_list_pagination_and_metadata_lookup(context) -> None:
    response = context.client.get(context.path, params={"limit": 10, "offset": 5})
    assert response.status_code == 200 and len(response.json()) == 1
    call = context.service.list_for_user.await_args.kwargs
    assert call["limit"] == 10 and call["offset"] == 5
    response = context.client.get(f"{context.path}/{context.document.id}")
    assert response.status_code == 200
    assert "storage_key" not in response.json()


@pytest.mark.parametrize("query", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_list_rejects_unbounded_pagination(context, query: dict) -> None:
    assert context.client.get(context.path, params=query).status_code == 422
    context.service.list_for_user.assert_not_awaited()


def test_download_is_private_attachment_and_closes_handle(context) -> None:
    handle = context.service.download_for_user.return_value[1]
    response = context.client.get(f"{context.path}/{context.document.id}/content")
    assert response.status_code == 200 and response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith(
        "attachment; filename*=UTF-8''"
    )
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert handle.closed


def test_download_closes_handle_when_client_disconnects(context) -> None:
    handle = io.BytesIO(PDF)
    response = DocumentContentResponse(context.document, handle)

    async def send(_message):
        raise OSError("client disconnected")

    async def receive():
        return {"type": "http.disconnect"}

    with pytest.raises(ClientDisconnect):
        asyncio.run(
            response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        )
    assert handle.closed


def test_delete_has_empty_204_response(context) -> None:
    response = context.client.delete(f"{context.path}/{context.document.id}")
    assert response.status_code == 204 and response.content == b""
    context.service.delete_for_user.assert_awaited_once()


@pytest.mark.parametrize(
    "method, suffix",
    [
        ("POST", ""),
        ("GET", ""),
        ("GET", "/id"),
        ("GET", "/id/content"),
        ("DELETE", "/id"),
    ],
)
def test_all_document_endpoints_require_bearer_token(
    context, method: str, suffix: str
) -> None:
    app.dependency_overrides.pop(get_current_user)
    path = context.path + suffix.replace("id", str(context.document.id))
    response = context.client.request(
        method,
        path,
        params={"filename": "resume.pdf"},
        content=PDF,
        headers={"Content-Type": "application/pdf"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"
    assert not context.service.mock_calls


@pytest.mark.parametrize(
    "status, code",
    [
        (404, "ORGANIZATION_NOT_FOUND"),
        (409, "DOCUMENT_ALREADY_EXISTS"),
        (413, "DOCUMENT_TOO_LARGE"),
        (415, "UNSUPPORTED_DOCUMENT_TYPE"),
        (503, "DOCUMENT_STORAGE_UNAVAILABLE"),
    ],
)
def test_domain_errors_keep_the_standard_contract(
    context, status: int, code: str
) -> None:
    context.service.upload.side_effect = AppError(
        code=code, message="Safe message.", status_code=status
    )
    response = context.client.post(
        context.path, params={"filename": "resume.pdf"}, content=PDF
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_openapi_describes_raw_pdf_upload_and_private_metadata() -> None:
    schema = app.openapi()
    operation = schema["paths"][
        "/organizations/{organization_id}/candidates/{candidate_id}/documents"
    ]["post"]
    assert (
        operation["requestBody"]["content"]["application/pdf"]["schema"]["format"]
        == "binary"
    )
    assert (
        "storage_key"
        not in schema["components"]["schemas"]["CandidateDocumentRead"]["properties"]
    )
