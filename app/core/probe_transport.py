"""Small HTTP/1.1 JSON probes to existing local health routes only."""

import json
import math
import re
import socket
import time
from urllib.parse import urlsplit

from app.core.probe_metrics import ProbeSample


def local_target(base_url: str) -> tuple[str, int]:
    if not isinstance(base_url, str) or any(ord(char) <= 32 for char in base_url) or any(
        char in base_url for char in ("\\", "%", "?", "#")
    ):
        raise ValueError("A local API origin is required.")
    try:
        url = urlsplit(base_url)
        host, port = url.hostname, 80 if url.port is None else url.port
        if url.scheme != "http" or url.username is not None or url.password is not None or url.path not in {"", "/"}:
            raise ValueError
        if host not in {"localhost", "127.0.0.1", "::1", "api"} or not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError("A local API origin is required.") from None
    return ("127.0.0.1" if host == "localhost" else host), port


def probe(base_url: str, path: str = "/ready", timeout: float = 2.0) -> ProbeSample:
    host, port = local_target(base_url)
    if path not in {"/health", "/ready"} or type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0.05 <= timeout <= 5:
        raise ValueError("Invalid probe route or timeout.")
    started = time.monotonic()
    deadline, status, outcome = started + timeout, 0, "invalid_response"
    authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            def remaining():
                value = deadline - time.monotonic()
                if value <= 0:
                    raise TimeoutError
                connection.settimeout(value)

            remaining()
            connection.sendall(f"GET {path} HTTP/1.1\r\nHost: {authority}\r\nConnection: close\r\nAccept: application/json\r\n\r\n".encode("ascii"))
            data = b""
            while b"\r\n\r\n" not in data:
                remaining()
                part = connection.recv(2048)
                if not part:
                    raise ValueError
                data += part
                if len(data) > 8192:
                    raise ValueError
            raw_headers, body = data.split(b"\r\n\r\n", 1)
            if len(raw_headers) > 4096:
                raise ValueError
            lines = raw_headers.decode("ascii").split("\r\n")
            if not re.fullmatch(r"HTTP/1\.[01] [1-5][0-9]{2}(?: [^\r\n]*)?", lines[0]):
                raise ValueError
            status = int(lines[0].split(" ")[1])
            headers = {}
            for line in lines[1:]:
                key, separator, value = line.partition(":")
                key = key.lower()
                if not separator or not re.fullmatch(r"[a-z0-9-]+", key) or key in headers:
                    raise ValueError
                headers[key] = value.strip()
            if status != 200:
                outcome = "http_error"
            else:
                length = headers.get("content-length", "")
                if not re.fullmatch(r"[0-9]{1,4}", length) or not 0 < int(length) <= 4096 or "transfer-encoding" in headers:
                    raise ValueError
                while len(body) < int(length):
                    remaining()
                    part = connection.recv(min(2048, int(length) - len(body)))
                    if not part:
                        raise ValueError
                    body += part
                remaining()
                payload = json.loads(body)
                valid = len(body) == int(length) and headers.get("content-type", "").split(";")[0].strip() == "application/json"
                valid = valid and re.fullmatch(r"[0-9a-f]{32}", headers.get("x-request-id", "")) is not None
                valid = valid and isinstance(payload, dict) and payload.get("status") == ("ready" if path == "/ready" else "ok")
                if path == "/ready":
                    valid = valid and payload == {"status": "ready"} and headers.get("cache-control") == "no-store"
                outcome = "ok" if valid else "invalid_response"
    except TimeoutError:
        outcome = "timeout"
    except OSError:
        outcome = "connection_error"
    except (ValueError, UnicodeError, RecursionError):
        outcome = "invalid_response"
    return ProbeSample((time.monotonic() - started) * 1000, outcome, status)
