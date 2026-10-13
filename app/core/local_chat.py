import asyncio
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.core.grounded_explanations import (
    MAX_PROMPT_BYTES,
    MODEL_TAG,
    ExplanationFailure,
    strict_json,
)
from app.core.semantic_embeddings import local_base_url

MAX_RESPONSE_BYTES = 256 * 1024
CHAT_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class ChatResult:
    payload: dict
    digest: str
    input_tokens: int
    output_tokens: int


class NoChatRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise ExplanationFailure("EXPLANATION_PROVIDER_REDIRECT")


class LocalChatGenerator:
    def __init__(self, base_url, *, timeout_seconds=120):
        self._url, self._timeout = local_base_url(base_url), timeout_seconds
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoChatRedirect())

    def _request(self, path, deadline, payload=None):
        import json

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ExplanationFailure("EXPLANATION_PROVIDER_TIMEOUT")
        request = urllib.request.Request(self._url + path,
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self._opener.open(request, timeout=remaining) as response:
                body = bytearray()
                while True:
                    if time.monotonic() >= deadline:
                        raise ExplanationFailure("EXPLANATION_PROVIDER_TIMEOUT")
                    part = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - len(body)))
                    if not part:
                        break
                    body.extend(part)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ExplanationFailure("EXPLANATION_PROVIDER_RESPONSE_INVALID")
            value = strict_json(body)
            if not isinstance(value, dict):
                raise ExplanationFailure("EXPLANATION_PROVIDER_RESPONSE_INVALID")
            return value
        except urllib.error.HTTPError as error:
            error.close()
            raise ExplanationFailure("EXPLANATION_PROVIDER_UNAVAILABLE") from None
        except (TimeoutError, OSError, urllib.error.URLError):
            raise ExplanationFailure("EXPLANATION_PROVIDER_UNAVAILABLE") from None
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise ExplanationFailure("EXPLANATION_PROVIDER_RESPONSE_INVALID") from None

    def _identity(self, deadline):
        models = self._request("/api/tags", deadline).get("models")
        if not isinstance(models, list):
            raise ExplanationFailure("EXPLANATION_PROVIDER_RESPONSE_INVALID")
        matches = [item for item in models if isinstance(item, dict) and item.get("name") == MODEL_TAG]
        if len(matches) != 1:
            raise ExplanationFailure("EXPLANATION_MODEL_NOT_INSTALLED")
        digest = matches[0].get("digest")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ExplanationFailure("EXPLANATION_MODEL_IDENTITY_INVALID")
        return digest

    def _generate(self, messages, schema):
        deadline = time.monotonic() + self._timeout
        digest = self._identity(deadline)
        response = self._request("/api/chat", deadline, {"model": MODEL_TAG,
            "messages": messages, "format": schema, "stream": False, "think": False,
            "keep_alive": 0, "options": {"num_ctx": 8192, "num_gpu": 0,
                "num_predict": 1024, "temperature": 0, "seed": 17}})
        message = response.get("message")
        if (response.get("model") != MODEL_TAG or response.get("done") is not True or
            response.get("done_reason") != "stop" or not isinstance(message, dict) or
            message.get("role") != "assistant" or message.get("tool_calls") or message.get("thinking") or
            not isinstance(message.get("content"), str) or len(message["content"].encode()) > 16384):
            raise ExplanationFailure("EXPLANATION_PROVIDER_RESPONSE_INVALID")
        counts = (response.get("prompt_eval_count"), response.get("eval_count"))
        if any(type(value) is not int or value < 1 for value in counts) or counts[0] > 8192 or counts[1] > 1024:
            raise ExplanationFailure("EXPLANATION_PROVIDER_RESPONSE_INVALID")
        try:
            payload = strict_json(message["content"])
        except (ValueError, RecursionError):
            raise ExplanationFailure("EXPLANATION_OUTPUT_INVALID") from None
        if self._identity(deadline) != digest:
            raise ExplanationFailure("EXPLANATION_MODEL_CHANGED")
        return ChatResult(payload, digest, *counts)

    async def generate(self, messages, schema):
        if len(messages) != 2 or len("".join(item["content"] for item in messages).encode()) > MAX_PROMPT_BYTES:
            raise ExplanationFailure("EXPLANATION_INPUT_TOO_LARGE")
        if CHAT_LOCK.locked():
            raise ExplanationFailure("EXPLANATION_PROVIDER_BUSY")
        await CHAT_LOCK.acquire()
        task = asyncio.create_task(asyncio.to_thread(self._generate, messages, schema))

        def release(done):
            if not done.cancelled():
                done.exception()
            CHAT_LOCK.release()

        try:
            async with asyncio.timeout(self._timeout):
                return await asyncio.shield(task)
        except TimeoutError:
            raise ExplanationFailure("EXPLANATION_PROVIDER_TIMEOUT") from None
        finally:
            if task.done():
                release(task)
            else:
                task.add_done_callback(release)
