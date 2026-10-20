import json
from unittest.mock import MagicMock

import pytest

from scripts.ai_quality_http import QualityHTTP


def response(monkeypatch, *, body=b'{"ok":true}', status=200, changed=None):
    import scripts.ai_quality_http as module

    headers = {"Content-Length": str(len(body)), "Content-Type": "application/json", "X-Request-ID": "a" * 32,
               "Cache-Control": "private, no-store"}
    headers.update(changed or {})
    reply = MagicMock(status=status)
    reply.getheader.side_effect = lambda key, default=None: headers.get(key, default)
    reply.read1.side_effect = [body, b""]
    connection = MagicMock()
    connection.getresponse.return_value = reply
    construct = MagicMock(return_value=connection)
    monkeypatch.setattr(module.http.client, "HTTPConnection", construct)
    return construct, connection


def test_private_http_bypasses_proxies_and_closes_connection(monkeypatch):
    construct, connection = response(monkeypatch)
    assert QualityHTTP("valid.token")._call("POST", "/organizations/abc/semantic-search", {"q": "پایتون"}) == (200, {"ok": True})
    construct.assert_called_once_with("api", 8000, timeout=180)
    sent = connection.request.call_args
    assert json.loads(sent.kwargs["body"])["q"] == "پایتون"
    assert sent.kwargs["headers"]["Authorization"] == "Bearer valid.token"
    connection.close.assert_called_once()


@pytest.mark.parametrize("changed", [{"Content-Length": "300000"}, {"Transfer-Encoding": "chunked"},
                                    {"Cache-Control": "public"}, {"X-Request-ID": "bad"}, {"Content-Type": "text/html"}])
def test_unbounded_or_nonprivate_response_is_rejected(monkeypatch, changed):
    _, connection = response(monkeypatch, changed=changed)
    with pytest.raises(ValueError):
        QualityHTTP("valid.token")._call("GET", "/private")
    connection.close.assert_called_once()


def test_duplicate_json_is_rejected_without_replaying_request(monkeypatch):
    _, connection = response(monkeypatch, body=b'{"key":1,"key":2}')
    with pytest.raises(ValueError):
        QualityHTTP("valid.token")._call("GET", "/private")
    connection.request.assert_called_once()
