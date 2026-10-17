"""Local bounded HTTP for synthetic operator workflows. Never retries a write."""

import json
import re
import socket
import time

from app.core.benchmark_metrics import PHASES
from app.core.probe_transport import local_target

MAX_BODY = 262144


class BenchmarkFailure(Exception):
    def __init__(self, code="request_failed"):
        self.code = code
        super().__init__(code)


class BenchmarkClient:
    def __init__(self, base_url, measurements, *, timeout=15):
        self.host, self.port = local_target(base_url)
        if type(timeout) not in {int, float} or not 1 <= timeout <= 30:
            raise ValueError("Invalid request timeout.")
        self.timeout, self.measurements = timeout, measurements

    def call(self, method, path, *, phase, expected=200, token=None, payload=None, binary=None):
        if phase not in PHASES or type(expected) is not int or not 100 <= expected <= 599:
            raise ValueError("Invalid workflow measurement.")
        if method not in {"GET", "POST", "PUT", "DELETE"} or not isinstance(path, str) or not re.fullmatch(
            r"/[a-zA-Z0-9/_.?=&-]{0,511}", path
        ) or any(part in {".", ".."} for part in path.split("?", 1)[0].split("/")) or path.startswith("//"):
            raise ValueError("Invalid workflow request.")
        if token is not None and (not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,4096}", token)):
            raise ValueError("Invalid workflow authorization.")
        if binary is not None and payload is not None:
            raise ValueError("Ambiguous request body.")
        body = binary if binary is not None else (json.dumps(payload, allow_nan=False).encode() if payload is not None else b"")
        if not isinstance(body, bytes) or len(body) > MAX_BODY:
            raise ValueError("Invalid workflow body.")
        authority = f"[{self.host}]:{self.port}" if ":" in self.host else f"{self.host}:{self.port}"
        headers = [f"{method} {path} HTTP/1.1", f"Host: {authority}", "Connection: close", "Accept: application/json",
                   "Content-Type: " + ("application/pdf" if binary is not None else "application/json"),
                   f"Content-Length: {len(body)}"]
        if token is not None:
            headers.append("Authorization: Bearer " + token)
        started = time.monotonic()
        deadline, failed = started + self.timeout, True
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as connection:
                def remaining():
                    seconds = deadline - time.monotonic()
                    if seconds <= 0:
                        raise TimeoutError
                    connection.settimeout(seconds)

                remaining()
                connection.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body)
                data = b""
                while b"\r\n\r\n" not in data:
                    remaining()
                    part = connection.recv(2048)
                    if not part:
                        raise ValueError
                    data += part
                    if len(data) > 8192:
                        raise ValueError
                raw, content = data.split(b"\r\n\r\n", 1)
                if len(raw) > 4096:
                    raise ValueError
                lines = raw.decode("ascii").split("\r\n")
                if not re.fullmatch(r"HTTP/1\.[01] [1-5][0-9]{2}(?: [^\r\n]*)?", lines[0]):
                    raise ValueError
                result_headers = {}
                for line in lines[1:]:
                    key, separator, value = line.partition(":")
                    key = key.lower()
                    if not separator or not re.fullmatch(r"[a-z0-9-]+", key) or key in result_headers:
                        raise ValueError
                    result_headers[key] = value.strip()
                length = result_headers.get("content-length", "0" if expected == 204 else "")
                if not re.fullmatch(r"[0-9]{1,6}", length) or int(length) > MAX_BODY or "transfer-encoding" in result_headers:
                    raise ValueError
                while len(content) < int(length):
                    remaining()
                    part = connection.recv(min(8192, int(length) - len(content)))
                    if not part:
                        raise ValueError
                    content += part
                remaining()
                if int(lines[0].split()[1]) != expected or len(content) != int(length) or not re.fullmatch(
                    r"[0-9a-f]{32}", result_headers.get("x-request-id", "")
                ):
                    raise ValueError
                if expected == 204:
                    if content:
                        raise ValueError
                    result = None
                else:
                    if result_headers.get("content-type", "").split(";")[0] != "application/json":
                        raise ValueError
                    result = json.loads(content)
                failed = False
                return result
        except (OSError, ValueError, UnicodeError, RecursionError):
            raise BenchmarkFailure("request_failed") from None
        finally:
            self.measurements.add(phase, (time.monotonic() - started) * 1000, failed=failed)
