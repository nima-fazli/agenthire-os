import io
import json
import logging
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.errors import register_exception_handlers
from app.core.logging import JsonFormatter, configure_logging
from app.db.session import engine


def test_json_formatter_returns_structured_log() -> None:
    record = logging.LogRecord(
        name="agenthire.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="test_event",
        args=(),
        exc_info=None,
    )

    formatted_log = JsonFormatter().format(record)
    log_data = json.loads(formatted_log)

    assert log_data["level"] == "INFO"
    assert log_data["logger"] == "agenthire.test"
    assert log_data["message"] == "test_event"
    assert "timestamp" in log_data


def test_configure_logging_configures_agenthire_logger() -> None:
    configure_logging(level="DEBUG")

    logger = logging.getLogger("agenthire")

    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0].formatter, JsonFormatter)
    assert logger.propagate is False


def test_exception_formatter_omits_sensitive_messages_and_source_lines() -> None:
    canary = "synthetic-private-exception-canary"
    try:
        raise RuntimeError(canary)
    except RuntimeError:
        record = logging.LogRecord(
            name="agenthire.errors",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="unhandled_exception",
            args=(),
            exc_info=sys.exc_info(),
        )

    formatted = JsonFormatter().format(record)
    exception = json.loads(formatted)["exception"]

    assert exception["type"] == "RuntimeError"
    assert exception["frames"]
    assert set(exception["frames"][-1]) == {"file", "line", "function"}
    assert canary not in formatted


def test_exception_formatter_omits_sensitive_exception_chains() -> None:
    canary = "synthetic-private-cause-canary"
    try:
        try:
            raise ValueError(canary)
        except ValueError as error:
            raise RuntimeError("synthetic outer failure") from error
    except RuntimeError:
        record = logging.LogRecord(
            name="agenthire.errors",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="unhandled_exception",
            args=(),
            exc_info=sys.exc_info(),
        )

    formatted = JsonFormatter().format(record)

    assert canary not in formatted
    assert "synthetic outer failure" not in formatted
    assert json.loads(formatted)["exception"]["type"] == "RuntimeError"


def test_database_error_string_hides_bound_parameters() -> None:
    canary = "synthetic-private-password-hash"
    error = IntegrityError(
        "INSERT INTO users (password_hash) VALUES (:password_hash)",
        {"password_hash": canary},
        RuntimeError("synthetic database failure"),
        hide_parameters=engine.sync_engine.hide_parameters,
    )

    assert canary not in str(error)


def test_unhandled_database_error_is_safe_in_response_and_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "synthetic-private-sql-canary"
    app = FastAPI(debug=False)
    register_exception_handlers(app)

    @app.get("/failure")
    async def failure() -> None:
        raise IntegrityError(
            "INSERT INTO users (password_hash) VALUES (:password_hash)",
            {"password_hash": canary},
            RuntimeError(canary),
        )

    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("agenthire.errors")

    monkeypatch.setattr(logger, "handlers", [handler])
    monkeypatch.setattr(logger, "propagate", False)
    monkeypatch.setattr(logger, "level", logging.ERROR)

    response = TestClient(app, raise_server_exceptions=False).get("/failure")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert canary not in response.text
    assert canary not in output.getvalue()
    assert json.loads(output.getvalue())["exception"]["type"] == "IntegrityError"


def test_uvicorn_message_arguments_and_exception_are_redacted() -> None:
    canary = "synthetic-private-server-message"
    try:
        raise RuntimeError(canary)
    except RuntimeError:
        record = logging.LogRecord(
            name="uvicorn.error", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="failed request %s", args=(canary,), exc_info=sys.exc_info(),
        )
    data = JsonFormatter().format(record)
    assert canary not in data
    assert json.loads(data)["message"] == "server_event"
    assert json.loads(data)["exception"]["type"] == "RuntimeError"


def test_configure_logging_disables_raw_access_log_and_formats_server_errors(monkeypatch):
    access = logging.getLogger("uvicorn.access")
    errors = logging.getLogger("uvicorn.error")
    monkeypatch.setattr(access, "disabled", False)
    monkeypatch.setattr(errors, "handlers", [])
    monkeypatch.setattr(errors, "propagate", True)
    configure_logging(level="INFO")
    assert access.disabled
    assert errors.propagate is False
    assert isinstance(errors.handlers[0].formatter, JsonFormatter)


def test_http_formatter_allows_bounded_fields_and_discards_unknown_data():
    record = logging.LogRecord("agenthire.http", logging.INFO, __file__, 1, "http_request_completed", (), None)
    record.request_id = "a" * 32
    record.method = "GET"
    record.route = "/items/{identifier}"
    record.status_code = 200
    record.outcome = "complete"
    record.duration_ms = 12.5
    record.authorization = "synthetic-private-token"
    record.query = "synthetic-private-query"
    data = JsonFormatter().format(record)
    assert "synthetic-private" not in data
    assert json.loads(data)["duration_ms"] == 12.5
    record.duration_ms = float("nan")
    record.route = "/bad?q=private"
    invalid = json.loads(JsonFormatter().format(record))
    assert "duration_ms" not in invalid and "route" not in invalid
