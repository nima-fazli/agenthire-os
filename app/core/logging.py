import json
import logging
import math
import sys
import traceback
from datetime import UTC, datetime
from typing import TextIO

from app.core.request_observability import (
    METHODS,
    REQUEST_ID,
    REQUEST_ID_PATTERN,
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Uvicorn can attach raw exceptions/request material to its own message.
        server_log = record.name.startswith("uvicorn")
        log_data: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": "server_event" if server_log else record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or REQUEST_ID.get()
        if isinstance(request_id, str) and REQUEST_ID_PATTERN.fullmatch(request_id):
            log_data["request_id"] = request_id
        if record.name == "agenthire.http":
            method = getattr(record, "method", "OTHER")
            log_data["method"] = method if isinstance(method, str) and method in METHODS else "OTHER"
            route = getattr(record, "route", "unmatched")
            if isinstance(route, str) and len(route) <= 200 and not any(
                char in route for char in ("\r", "\n", "?")
            ):
                log_data["route"] = route
            code = getattr(record, "status_code", 0)
            if type(code) is int and (code == 0 or 100 <= code <= 599):
                log_data["status_code"] = code
            outcome = getattr(record, "outcome", None)
            if outcome in {"complete", "error", "cancelled", "incomplete"}:
                log_data["outcome"] = outcome
            duration = getattr(record, "duration_ms", None)
            if type(duration) in {int, float} and math.isfinite(duration) and duration >= 0:
                log_data["duration_ms"] = duration
        if record.exc_info is not None:
            _, exception, exception_traceback = record.exc_info
            log_data["exception"] = {
                "type": type(exception).__name__,
                "frames": [
                    {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                    for frame in traceback.extract_tb(exception_traceback)
                ],
            }
        return json.dumps(log_data, ensure_ascii=False)


def configure_logging(*, level: str, stream: TextIO | None = None) -> None:
    handler = logging.StreamHandler(sys.stdout if stream is None else stream)
    handler.setFormatter(JsonFormatter())
    for name in ("agenthire", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.propagate = False
    # The replacement request event logs route templates, never raw query strings.
    logging.getLogger("uvicorn.access").disabled = True
