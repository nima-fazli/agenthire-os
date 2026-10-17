import asyncio
import io
import json
import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from app.core.errors import AppError, register_exception_handlers
from app.core.logging import JsonFormatter
from app.core.request_observability import (
    REQUEST_ID,
    REQUEST_ID_PATTERN,
    RequestObservabilityMiddleware,
)


@pytest.fixture
def output(monkeypatch):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    for name in ("agenthire.http", "agenthire.errors"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "handlers", [handler])
        monkeypatch.setattr(logger, "propagate", False)
        monkeypatch.setattr(logger, "level", logging.INFO)
    return stream


def records(output):
    return [json.loads(line) for line in output.getvalue().splitlines()]


def application():
    app = FastAPI()
    app.add_middleware(RequestObservabilityMiddleware)
    register_exception_handlers(app)

    @app.get("/items/{identifier}")
    async def item(identifier: str):
        logging.getLogger("agenthire.http").info("service_event")
        return {"ok": True}

    @app.get("/handled")
    async def handled():
        raise AppError(code="SYNTHETIC", message="Expected failure.", status_code=409)

    @app.get("/crash")
    async def crash():
        raise RuntimeError("synthetic-private-exception")

    @app.get("/stream")
    async def stream():
        async def chunks():
            yield b"first"
            yield b"second"
        return StreamingResponse(chunks())

    return app


def test_request_id_is_server_generated_and_logs_have_no_private_request_material(output):
    canary = "synthetic-private-query-token-body"
    client = TestClient(application())
    first = client.get(
        f"/items/{canary}?q={canary}",
        headers={"Authorization": "Bearer " + canary, "X-Request-ID": canary},
    )
    second = client.get("/items/another")
    first_id, second_id = first.headers["x-request-id"], second.headers["x-request-id"]
    assert REQUEST_ID_PATTERN.fullmatch(first_id) and first_id != second_id
    events = [row for row in records(output) if row["message"] == "http_request_completed"]
    assert events[0]["route"] == "/items/{identifier}"
    assert events[0]["request_id"] == first_id
    assert events[0]["status_code"] == 200 and events[0]["duration_ms"] >= 0
    assert canary not in output.getvalue()
    assert REQUEST_ID.get() is None


@pytest.mark.parametrize("path,code", [("/handled", 409), ("/crash", 500), ("/missing", 404)])
def test_handled_unhandled_and_unknown_responses_keep_correlation(path, code, output):
    response = TestClient(application(), raise_server_exceptions=False).get(path)
    assert response.status_code == code
    request_id = response.headers["x-request-id"]
    assert REQUEST_ID_PATTERN.fullmatch(request_id)
    assert all(row.get("request_id") == request_id for row in records(output))
    assert "synthetic-private-exception" not in output.getvalue() + response.text


def test_stream_content_and_completion_are_preserved(output):
    response = TestClient(application()).get("/stream")
    assert response.content == b"firstsecond"
    assert records(output)[-1]["outcome"] == "complete"


def test_pure_asgi_does_not_buffer_or_read_request_body_and_preserves_messages(output):
    scope = {
        "type": "http", "method": "POST", "path": "/private", "query_string": b"q=private",
        "route": SimpleNamespace(path="/private"),
    }
    messages = []
    payload = b"synthetic-private-stream"

    async def forbidden_receive():
        pytest.fail("Middleware must not read a body itself.")

    async def send(message):
        messages.append(message)

    async def downstream(scope, receive, send):
        assert receive is forbidden_receive
        await send({"type": "http.response.start", "status": 200, "headers": [(b"x-request-id", b"forged")]})
        await send({"type": "http.response.body", "body": payload, "more_body": True})
        await send({"type": "http.response.body", "body": b"end"})

    asyncio.run(RequestObservabilityMiddleware(downstream)(scope, forbidden_receive, send))
    assert messages[1]["body"] is payload
    assert dict(messages[0]["headers"])[b"x-request-id"] != b"forged"
    assert records(output)[-1]["outcome"] == "complete"
    assert "synthetic-private-stream" not in output.getvalue()


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError], ids=["stream_failure", "cancelled"])
def test_stream_failure_and_cancellation_are_observable_and_propagated(error, output):
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise error("synthetic-private-failure")

    async def send(_):
        pass

    with pytest.raises(error):
        asyncio.run(RequestObservabilityMiddleware(downstream)(
            {"type": "http", "method": "GET"}, None, send,
        ))
    event = records(output)[-1]
    assert event["status_code"] == 200
    assert event["outcome"] == ("cancelled" if error is asyncio.CancelledError else "error")
    assert REQUEST_ID.get() is None
    assert "synthetic-private-failure" not in output.getvalue()


def test_non_http_scope_bypasses_http_logging(output):
    marker = []

    async def downstream(scope, receive, send):
        marker.append(scope["type"])

    asyncio.run(RequestObservabilityMiddleware(downstream)({"type": "lifespan"}, None, None))
    assert marker == ["lifespan"] and output.getvalue() == ""


def test_concurrent_requests_keep_distinct_contexts(output):
    async def downstream(scope, receive, send):
        scope["route"] = SimpleNamespace(path="/items/{identifier}")
        before = REQUEST_ID.get()
        await asyncio.sleep(0)
        assert REQUEST_ID.get() == before
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def run():
        async def send(_):
            pass
        middleware = RequestObservabilityMiddleware(downstream)
        await asyncio.gather(*(middleware({"type": "http", "method": "GET"}, None, send) for _ in range(20)))
        assert REQUEST_ID.get() is None

    asyncio.run(run())
    assert len({row["request_id"] for row in records(output)}) == 20


def test_no_response_is_logged_as_incomplete(output):
    async def downstream(*_):
        pass

    asyncio.run(RequestObservabilityMiddleware(downstream)({"type": "http", "method": "UNKNOWN"}, None, None))
    assert records(output)[-1]["outcome"] == "incomplete"
    assert records(output)[-1]["status_code"] == 0
    assert records(output)[-1]["method"] == "OTHER"
