import asyncio
import logging
import re
import time
from contextvars import ContextVar
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID: ContextVar[str | None] = ContextVar("agenthire_request_id", default=None)
REQUEST_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
logger = logging.getLogger("agenthire.http")


def request_id_from_scope(scope: Scope) -> str | None:
    value = scope.get("state", {}).get("request_id")
    return value if isinstance(value, str) and REQUEST_ID_PATTERN.fullmatch(value) else None


class RequestObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        context = REQUEST_ID.set(request_id)
        started = time.perf_counter()
        status_code = 0
        finished = False
        outcome = "complete"

        async def observe_send(message: Message) -> None:
            nonlocal status_code, finished
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [
                    (key, value) for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                message = {**message, "headers": [*headers, (b"x-request-id", request_id.encode("ascii"))]}
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                finished = True
            await send(message)

        try:
            await self.app(scope, receive, observe_send)
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:
            outcome = "error"
            if not status_code:
                status_code = 500
            raise
        finally:
            try:
                if outcome == "complete" and not finished:
                    outcome = "incomplete"
                route = getattr(scope.get("route"), "path", None)
                logger.info("http_request_completed", extra={
                    "request_id": request_id,
                    "method": scope.get("method") if scope.get("method") in METHODS else "OTHER",
                    "route": route if isinstance(route, str) else "unmatched",
                    "status_code": status_code,
                    "outcome": outcome,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                })
            finally:
                REQUEST_ID.reset(context)
