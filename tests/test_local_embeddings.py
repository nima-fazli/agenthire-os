import asyncio
import hashlib
import io
import json
import math
import runpy
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.core.config import Settings
from app.core.local_embeddings import LocalEmbeddingEncoder
from app.core.semantic_embeddings import (
    DIMENSIONS,
    MODEL_TAG,
    EmbeddingFailure,
    EmbeddingVector,
    ModelIdentity,
    SourceChunk,
    local_base_url,
    normalized_vector,
    validate_chunks,
)
from app.models.document_embeddings import DocumentEmbedding, DocumentEmbeddingJob
from app.schemas.document_embeddings import EmbeddingRequest

IDENTITY = ModelIdentity("a" * 64)
VECTOR = [2.0] + [0.0] * (DIMENSIONS - 1)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]", "ollama"])
def test_only_explicit_local_endpoints_are_allowed(host):
    assert local_base_url(f"http://{host}:11434/") == f"http://{host}:11434"


@pytest.mark.parametrize("url", [
    "https://ollama.com:11434", "http://example.com:11434", "http://169.254.169.254:11434",
    "http://localhost:80", "http://localhost:11434/api", "http://user:password@localhost:11434",
    "http://localhost:11434?proxy=true", "http://localhost:11434#x", "http://local\nhost:11434",
], ids=["cloud", "public", "metadata", "port", "path", "credentials", "query", "fragment", "control"])
def test_remote_or_indirect_endpoints_are_rejected(url):
    with pytest.raises(ValueError):
        Settings(_env_file=None, embedding_base_url=url)


@pytest.mark.parametrize("value", [[], [1.0], [0.0] * DIMENSIONS,
    [float("nan")] * DIMENSIONS, [float("inf")] * DIMENSIONS,
    [True] * DIMENSIONS, ["1"] * DIMENSIONS, [10**1000] * DIMENSIONS],
    ids=["empty", "dimension", "zero", "nan", "infinite", "boolean", "string", "overflow"])
def test_unusable_vectors_are_rejected_without_echoing_input(value):
    with pytest.raises(EmbeddingFailure, match="EMBEDDING_VECTOR_INVALID"):
        normalized_vector(value)


def test_normalization_type_round_trip_and_reflection():
    vector = normalized_vector(VECTOR)
    assert math.isclose(math.hypot(*vector), 1)
    kind = EmbeddingVector(1024)
    encoded = kind.bind_processor(postgresql.dialect())(VECTOR)
    assert kind.result_processor(None, None)(encoded) == vector
    reflected = postgresql.dialect()._reflect_type(
        "vector(1024)", SimpleNamespace(enums={}, domains={}), "embedding", None
    )
    assert reflected.dimensions == 1024


@pytest.mark.parametrize("change", ["hash", "position", "count", "length"])
def test_chunk_provenance_and_completeness_are_validated(change):
    text = "رزومهٔ Python"
    chunk = SourceChunk(0, text, hashlib.sha256(text.encode()).hexdigest())
    if change == "hash":
        chunk = SourceChunk(0, text, "f" * 64)
    elif change == "position":
        chunk = SourceChunk(1, text, chunk.sha256)
    elif change == "length":
        chunk = SourceChunk(0, "x" * 4001, hashlib.sha256(("x" * 4001).encode()).hexdigest())
    with pytest.raises(EmbeddingFailure):
        validate_chunks((chunk,), 2 if change == "count" else 1)


def test_schema_and_migration_freeze_matching_vector_constraints():
    ddl = str(CreateTable(DocumentEmbedding.__table__).compile(dialect=postgresql.dialect()))
    assert "vector(1024)" in ddl and "vector_norm" in ddl
    assert "fk_document_embeddings_job_source" in ddl and "fk_document_embeddings_chunk" in ddl
    stream = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": stream})
    migration = runpy.run_path(str(Path(__file__).parents[1] / "migrations/versions/0016_document_embeddings.py"))
    with Operations.context(context):
        migration["upgrade"]()
    sql = stream.getvalue()
    for table in (DocumentEmbeddingJob.__table__, DocumentEmbedding.__table__):
        assert f"CREATE TABLE {table.name}" in sql
        for constraint in table.constraints:
            assert constraint.name in sql


def test_feature_is_opt_in_and_lease_covers_the_entire_batch():
    assert not Settings(_env_file=None).semantic_enabled
    with pytest.raises(ValidationError, match="30-second margin"):
        Settings(_env_file=None, embedding_timeout_seconds=120, embedding_lease_seconds=300)
    with pytest.raises(ValidationError):
        EmbeddingRequest(model="cloud")
    with pytest.raises(ValidationError):
        EmbeddingRequest(retry="true")


@pytest.fixture
def server():
    state = {"digest": IDENTITY.digest, "payloads": [], "redirect": False, "vectors": [VECTOR], "model": MODEL_TAG, "http_error": False, "change_after": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, data):
            content = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            if state["http_error"]:
                self.send_error(503)
            elif state["redirect"]:
                self.send_response(302)
                self.send_header("Location", "https://example.com/private")
                self.end_headers()
            else:
                self.respond({"models": [{"name": MODEL_TAG, "digest": state["digest"]}]})

        def do_POST(self):
            state["payloads"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.respond({"model": state["model"], "embeddings": state["vectors"]})
            if state["change_after"]:
                state["digest"] = "b" * 64

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    encoder = LocalEmbeddingEncoder("http://127.0.0.1:11434")
    encoder._url = f"http://127.0.0.1:{httpd.server_port}"
    yield encoder, state
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_real_http_transport_pins_model_disables_truncation_and_preserves_persian(server):
    encoder, state = server
    result = asyncio.run(encoder.encode(("رزومهٔ Python",), IDENTITY))
    assert result == (normalized_vector(VECTOR),)
    payload = state["payloads"][0]
    assert payload["input"] == ["رزومهٔ Python"]
    assert payload["truncate"] is False and payload["dimensions"] == 1024
    assert payload["options"]["num_gpu"] == 0


def test_provider_deadline_discards_late_responses(monkeypatch):
    encoder = LocalEmbeddingEncoder("http://127.0.0.1:11434", timeout_seconds=0.01)

    def late(*args):
        threading.Event().wait(0.05)
        return {"models": [{"name": MODEL_TAG, "digest": IDENTITY.digest}]}

    monkeypatch.setattr(encoder, "_request", late)
    with pytest.raises(EmbeddingFailure, match="EMBEDDING_PROVIDER_TIMEOUT"):
        asyncio.run(encoder.identity())


@pytest.mark.parametrize("problem", ["redirect", "changed", "dimension", "model", "count", "http_error", "change_after"])
def test_incompatible_model_and_redirect_fail_closed(server, problem):
    encoder, state = server
    if problem == "redirect":
        state["redirect"] = True
    elif problem in {"http_error", "change_after"}:
        state[problem] = True
    elif problem == "changed":
        state["digest"] = "b" * 64
    elif problem == "dimension":
        state["vectors"] = [[1]]
    elif problem == "count":
        state["vectors"] = []
    else:
        state["model"] = "cloud"
    with pytest.raises(EmbeddingFailure):
        asyncio.run(encoder.encode(("synthetic",), IDENTITY))
    if problem in {"redirect", "changed"}:
        assert not state["payloads"]
