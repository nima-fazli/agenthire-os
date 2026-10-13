import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import Protocol

from app.core.semantic_embeddings import (
    DIMENSIONS,
    MAX_TEXT_CHARS,
    MODEL_TAG,
    EmbeddingFailure,
    ModelIdentity,
    local_base_url,
    normalized_vector,
)

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class EmbeddingEncoder(Protocol):
    async def identity(self) -> ModelIdentity: ...
    async def encode(
        self, texts: tuple[str, ...], identity: ModelIdentity
    ) -> tuple[tuple[float, ...], ...]: ...


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise EmbeddingFailure("EMBEDDING_PROVIDER_REDIRECT")


class LocalEmbeddingEncoder:
    def __init__(self, base_url: str, *, timeout_seconds: int = 60) -> None:
        self._url = local_base_url(base_url)
        self._timeout = timeout_seconds
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )

    def _request(self, path: str, payload: dict | None = None) -> dict:
        deadline = time.monotonic() + self._timeout
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._url + path,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                content = bytearray()
                while True:
                    if time.monotonic() >= deadline:
                        raise EmbeddingFailure("EMBEDDING_PROVIDER_TIMEOUT")
                    chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - len(content)))
                    if not chunk:
                        break
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise EmbeddingFailure("EMBEDDING_PROVIDER_RESPONSE_INVALID")
            result = json.loads(content)
            if not isinstance(result, dict):
                raise EmbeddingFailure("EMBEDDING_PROVIDER_RESPONSE_INVALID")
            return result
        except urllib.error.HTTPError as error:
            error.close()
            raise EmbeddingFailure("EMBEDDING_PROVIDER_UNAVAILABLE") from error
        except (TimeoutError, OSError, urllib.error.URLError) as error:
            raise EmbeddingFailure("EMBEDDING_PROVIDER_UNAVAILABLE") from error
        except (ValueError, UnicodeDecodeError) as error:
            raise EmbeddingFailure("EMBEDDING_PROVIDER_RESPONSE_INVALID") from error

    async def _call(self, path: str, payload: dict | None = None) -> dict:
        try:
            async with asyncio.timeout(self._timeout):
                return await asyncio.to_thread(self._request, path, payload)
        except TimeoutError as error:
            raise EmbeddingFailure("EMBEDDING_PROVIDER_TIMEOUT") from error

    async def identity(self) -> ModelIdentity:
        result = await self._call("/api/tags")
        models = result.get("models")
        if not isinstance(models, list):
            raise EmbeddingFailure("EMBEDDING_PROVIDER_RESPONSE_INVALID")
        matches = [item for item in models if isinstance(item, dict) and item.get("name") == MODEL_TAG]
        if len(matches) != 1 or not isinstance(matches[0].get("digest"), str):
            raise EmbeddingFailure("EMBEDDING_MODEL_NOT_INSTALLED")
        return ModelIdentity(matches[0]["digest"])

    async def encode(
        self, texts: tuple[str, ...], identity: ModelIdentity
    ) -> tuple[tuple[float, ...], ...]:
        if not 1 <= len(texts) <= 8 or any(
            not isinstance(text, str) or not 1 <= len(text) <= MAX_TEXT_CHARS
            for text in texts
        ):
            raise EmbeddingFailure("EMBEDDING_INPUT_INVALID")
        if await self.identity() != identity:
            raise EmbeddingFailure("EMBEDDING_MODEL_CHANGED")
        response = await self._call(
            "/api/embed",
            {
                "model": MODEL_TAG,
                "input": list(texts),
                "truncate": False,
                "dimensions": DIMENSIONS,
                "keep_alive": "5m",
                "options": {"num_ctx": 8192, "num_gpu": 0},
            },
        )
        values = response.get("embeddings")
        if response.get("model") != MODEL_TAG or not isinstance(values, list) or len(values) != len(texts):
            raise EmbeddingFailure("EMBEDDING_PROVIDER_RESPONSE_INVALID")
        vectors = tuple(normalized_vector(value) for value in values)
        if await self.identity() != identity:
            raise EmbeddingFailure("EMBEDDING_MODEL_CHANGED")
        return vectors
