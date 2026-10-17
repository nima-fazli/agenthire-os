import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from app.core.benchmark_metrics import Measurements
from scripts.benchmark_http import BenchmarkClient, BenchmarkFailure


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.server.observed = (self.path, self.headers.get("Authorization"),
                                    self.rfile.read(int(self.headers.get("Content-Length", 0))))
            status = 302 if self.path == "/redirect" else (500 if self.path == "/failure" else 201)
            payload = b'{"private":"must-not-be-printed"}' if status != 201 else json.dumps({"created": True}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Request-ID", "a" * 32)
            self.send_header("Location", "/external")
            self.end_headers()
            self.wfile.write(payload)

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield http
    finally:
        http.shutdown()
        http.server_close()
        thread.join(2)


def test_real_local_request_keeps_auth_out_of_metrics(server):
    metrics = Measurements()
    client = BenchmarkClient(f"http://127.0.0.1:{server.server_port}", metrics)
    assert client.call("POST", "/created", phase="candidate", expected=201,
                       token="secret.jwt.value", payload={"name": "synthetic"}) == {"created": True}
    assert server.observed[1] == "Bearer secret.jwt.value"
    assert json.loads(server.observed[2]) == {"name": "synthetic"}
    assert "secret" not in json.dumps(metrics.report())


@pytest.mark.parametrize("path", ["/redirect", "/failure"])
def test_error_body_is_never_exposed_or_retried(server, path):
    metrics = Measurements()
    client = BenchmarkClient(f"http://127.0.0.1:{server.server_port}", metrics)
    with pytest.raises(BenchmarkFailure) as caught:
        client.call("POST", path, phase="candidate", expected=201, payload={})
    assert str(caught.value) == "request_failed"
    assert metrics.report()["candidate"]["samples"] == 1
    assert metrics.report()["candidate"]["failed"] == 1


@pytest.mark.parametrize("url", ["https://api", "http://example.com", "http://user:password@api", "http://api/path"])
def test_external_or_ambiguous_origins_never_open_a_connection(url, monkeypatch):
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network used"))
    with pytest.raises(ValueError):
        BenchmarkClient(url, Measurements())


@pytest.mark.parametrize("path", ["//api/private", "/../private", "/a\r\nAuthorization:x", "/a%2fb"])
def test_invalid_paths_fail_before_network(path, monkeypatch):
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network used"))
    with pytest.raises(ValueError):
        BenchmarkClient("http://api:8000", Measurements()).call("POST", path, phase="candidate")
