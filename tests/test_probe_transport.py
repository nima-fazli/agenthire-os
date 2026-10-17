import json
import socketserver
import threading
import time
from dataclasses import asdict

import pytest

from app.core.probe_transport import local_target, probe


def response(body=b'{"status":"ready"}', *, status=200, extra=b"", length=None):
    size = len(body) if length is None else length
    return (f"HTTP/1.1 {status} Result\r\nContent-Length: {size}\r\n".encode() +
            b"Content-Type: application/json\r\nCache-Control: no-store\r\nX-Request-ID: " +
            b"a" * 32 + b"\r\n" + extra + b"\r\n" + body)


@pytest.fixture
def serve():
    servers = []

    def start(payload, *, drip=False):
        requests = []

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(1)
                data = b""
                while b"\r\n\r\n" not in data:
                    part = self.request.recv(2048)
                    if not part:
                        return
                    data += part
                requests.append(data)
                try:
                    for part in ([bytes([byte]) for byte in payload] if drip else [payload]):
                        self.request.sendall(part)
                        if drip:
                            time.sleep(0.01)
                except OSError:
                    pass

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True

        server = Server(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_address[1]}", requests

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join()


def test_real_socket_ignores_proxies_and_sends_no_credentials(serve, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://private-proxy.invalid")
    base, requests = serve(response())
    assert probe(base).outcome == "ok"
    assert len(requests) == 1 and requests[0].startswith(b"GET /ready HTTP/1.1")
    assert b"Authorization" not in requests[0] and b"Cookie" not in requests[0]


@pytest.mark.parametrize("payload", [
    response(b'{"status":"ready","private":"secret"}'),
    response(extra=b"X-Request-ID: forged\r\n"), response(length=4097),
    response(b"private-non-json"), response(extra=b"Transfer-Encoding: chunked\r\n"),
    response(extra=b"X-Long: " + b"a" * 5000 + b"\r\n"),
])
def test_invalid_private_or_oversized_response_is_safe(serve, payload):
    base, _ = serve(payload)
    sample = probe(base)
    assert sample.outcome == "invalid_response"
    assert "private" not in json.dumps(asdict(sample))


@pytest.mark.parametrize("status", [302, 503])
def test_redirect_and_failure_are_not_followed_or_exposed(serve, status):
    base, requests = serve(response(b"private-error", status=status, extra=b"Location: http://foreign.invalid\r\n"))
    sample = probe(base)
    assert sample.outcome == "http_error" and sample.status_code == status
    assert len(requests) == 1 and "private" not in json.dumps(asdict(sample))


def test_whole_response_deadline_bounds_a_slow_header(serve):
    base, _ = serve(response(), drip=True)
    started = time.monotonic()
    assert probe(base, timeout=0.05).outcome == "timeout"
    assert time.monotonic() - started < 1


@pytest.mark.parametrize("value", [
    "https://localhost:8000", "http://foreign.invalid", "http://localhost:0", "http://localhost:65536",
    "http://user:secret@localhost", "http://localhost/private", "http://localhost?q=secret",
    "http://localhost/#secret", "http://localhost%2f", "http://localhost\n", "file:///private",
])
def test_unsafe_origin_is_rejected_before_network(value):
    with pytest.raises(ValueError):
        local_target(value)
