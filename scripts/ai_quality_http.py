"""Bounded requests to the internal test API without proxies, redirects, or retries."""

import asyncio
import http.client
import json
import re
import time

from app.core.grounded_explanations import strict_json


class QualityHTTP:
    def __init__(self, token, *, timeout=180):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,4096}", token) or not 1 <= timeout <= 180:
            raise ValueError("invalid_quality_http_client")
        self.token, self.timeout = token, timeout

    async def call(self, method, path, payload=None):
        return await asyncio.to_thread(self._call, method, path, payload)

    def _call(self, method, path, payload=None):
        if method not in {"GET", "PUT", "POST"} or not re.fullmatch(r"/[A-Za-z0-9/?=&_-]{1,511}", path):
            raise ValueError("invalid_quality_http_request")
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() if payload is not None else None
        if body is not None and len(body) > 65536:
            raise ValueError("quality_request_too_large")
        connection = http.client.HTTPConnection("api", 8000, timeout=self.timeout)
        deadline = time.monotonic() + self.timeout
        try:
            connection.connect()
            transport = connection.sock
            connection.request(method, path, body=body, headers={"Authorization": "Bearer " + self.token,
                               "Content-Type": "application/json", "Accept": "application/json", "Connection": "close"})
            response = connection.getresponse()
            length = response.getheader("Content-Length", "")
            if (response.getheader("Transfer-Encoding") or not re.fullmatch(r"[0-9]{1,7}", length)
                    or int(length) > 262144 or response.getheader("Content-Type", "").split(";")[0] != "application/json"
                    or not re.fullmatch(r"[0-9a-f]{32}", response.getheader("X-Request-ID", ""))):
                raise ValueError("quality_http_contract_failed")
            if response.status == 200 and response.getheader("Cache-Control") != "private, no-store":
                raise ValueError("quality_http_cache_policy_failed")
            data = bytearray()
            while len(data) < int(length):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                transport.settimeout(remaining)
                part = response.read1(min(8192, int(length) - len(data)))
                if not part:
                    raise ValueError("quality_http_body_incomplete")
                data.extend(part)
            if time.monotonic() > deadline:
                raise TimeoutError
            result = strict_json(data)
            if not isinstance(result, dict):
                raise TypeError("quality_http_json_invalid")
            return response.status, result
        except (OSError, http.client.HTTPException):
            raise ValueError("quality_http_unavailable") from None
        finally:
            connection.close()
