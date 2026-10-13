import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core.grounded_explanations import MODEL_TAG, ExplanationFailure, prepare
from app.core.local_chat import CHAT_LOCK, LocalChatGenerator
from scripts.grounded_explanations_evaluation import example_snapshot


@pytest.fixture
def server(monkeypatch):
    state = {"digest": "a" * 64, "payloads": [], "redirect": False, "http_error": False,
             "change_after": False, "done_reason": "stop", "model": MODEL_TAG,
             "thinking": "", "content": '{"quotes":[{"criterion":"skill","source":"s0","quote":"Python"}]}'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, value):
            body = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if state["redirect"]:
                self.send_response(302)
                self.send_header("Location", "https://foreign.example/private")
                self.end_headers()
            elif state["http_error"]:
                self.send_error(503)
            else:
                self.respond({"models": [{"name": MODEL_TAG, "digest": state["digest"]}]})

        def do_POST(self):
            state["payloads"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.respond({"model": state["model"], "done": True, "done_reason": state["done_reason"],
                "prompt_eval_count": 100, "eval_count": 30,
                "message": {"role": "assistant", "content": state["content"], "thinking": state["thinking"]}})
            if state["change_after"]:
                state["digest"] = "b" * 64

    monkeypatch.setenv("HTTP_PROXY", "http://foreign.example:9999")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    client = LocalChatGenerator("http://127.0.0.1:11434")
    client._url = f"http://127.0.0.1:{httpd.server_port}"
    try:
        yield client, state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def test_http_transport_is_cpu_only_structured_nonstreaming_and_digest_pinned(server):
    client, state = server
    _, messages, schema = prepare(example_snapshot())
    result = asyncio.run(client.generate(messages, schema))
    payload = state["payloads"][0]
    assert result.digest == "a" * 64 and result.payload["quotes"][0]["quote"] == "Python"
    assert payload["format"] == schema and payload["think"] is False and payload["stream"] is False
    assert payload["keep_alive"] == 0 and payload["options"]["num_gpu"] == 0
    assert payload["options"]["num_predict"] == 1024


@pytest.mark.parametrize("issue", ["redirect", "http_error", "change_after", "done_reason", "model", "thinking", "content", "digest"])
def test_incompatible_model_truncation_reasoning_and_ambiguous_output_fail_closed(server, issue):
    client, state = server
    values = {"done_reason": "length", "model": "foreign", "thinking": "private reasoning",
              "content": '{"quotes":[],"quotes":[]}', "digest": "bad"}
    state[issue] = values.get(issue, True)
    _, messages, schema = prepare(example_snapshot())
    with pytest.raises(ExplanationFailure):
        asyncio.run(client.generate(messages, schema))
    if issue in {"redirect", "http_error", "digest"}:
        assert not state["payloads"]


@pytest.mark.parametrize("cancel", [True, False])
def test_cancelled_or_timed_out_transport_keeps_capacity_occupied_until_thread_finishes(monkeypatch, cancel):
    client = LocalChatGenerator("http://127.0.0.1:11434", timeout_seconds=5 if cancel else 0.02)
    entered, finish = threading.Event(), threading.Event()

    def blocked(*args):
        entered.set()
        finish.wait(1)
        raise ExplanationFailure("EXPLANATION_PROVIDER_UNAVAILABLE")

    monkeypatch.setattr(client, "_generate", blocked)
    _, messages, schema = prepare(example_snapshot())

    async def run():
        first = asyncio.create_task(client.generate(messages, schema))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        if cancel:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            with pytest.raises(ExplanationFailure, match="TIMEOUT"):
                await first
        try:
            with pytest.raises(ExplanationFailure, match="BUSY"):
                await client.generate(messages, schema)
        finally:
            finish.set()
        async with asyncio.timeout(2):
            while CHAT_LOCK.locked():
                await asyncio.sleep(0.001)

    asyncio.run(run())
