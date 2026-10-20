import asyncio
import math
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings
from app.models import DocumentChunk, DocumentEmbedding, DocumentEmbeddingJob
from scripts.ai_quality_contract import load_reference
from scripts.ai_quality_fixture import (
    FixtureEncoder,
    QualityFixture,
    require_test_database,
    sha,
    verify_source,
)


def witness():
    prefix, text = "عنوان 👩🏽‍💻\n", "پایتون فقط تمرین بود؛ تجربهٔ حرفه‌ای نیست."
    source = {"document_id": uuid4(), "chunk_set_id": uuid4(), "text": prefix + text,
              "parts": [prefix, text], "document_sha": "a" * 64}
    value = SimpleNamespace(document_id=source["document_id"], chunk_set_id=source["chunk_set_id"],
        chunk_position=1, start_offset=len(prefix), end_offset=len(prefix + text), quote=text,
        quote_sha256=sha(text), chunk_sha256=sha(text), source_text_sha256=sha(prefix + text),
        source_document_sha256=source["document_sha"])
    return source, value


@pytest.mark.parametrize("field", ["document_id", "chunk_set_id", "start_offset", "end_offset", "quote", "quote_sha256",
                                  "chunk_sha256", "source_text_sha256", "source_document_sha256", "chunk_position"])
def test_independent_source_proof_detects_each_changed_component(field):
    source, value = witness()
    assert verify_source(value, source, citation=True)
    original = getattr(value, field)
    setattr(value, field, original + 1 if type(original) is int else "changed")
    assert not verify_source(value, source, citation=True)


def test_codepoint_offsets_are_not_utf8_bytes_or_utf16_units():
    source, value = witness()
    assert len(source["parts"][0]) != len(source["parts"][0].encode())
    value.start_offset = len(source["parts"][0].encode("utf-16-le")) // 2
    assert not verify_source(value, source, citation=True)


def test_quality_refuses_normal_database_and_arbitrary_projects():
    settings = get_settings().model_copy(update={"environment": "test", "postgres_host": "postgres",
                                               "postgres_db": "agenthire_ci", "postgres_user": "agenthire_ci"})
    require_test_database(settings, "agenthire-ci-" + "a" * 32)
    for key, bad in (("environment", "local"), ("postgres_db", "agenthire"), ("postgres_user", "normal"),
                     ("postgres_host", "127.0.0.1")):
        with pytest.raises(ValueError):
            require_test_database(settings.model_copy(update={key: bad}))
    with pytest.raises(ValueError):
        require_test_database(settings, "agenthire-os")


def test_seed_has_complete_scoped_embedding_rows_and_cleanup_only_exact_ids():
    session = AsyncMock()
    session.add, session.add_all = MagicMock(), MagicMock()

    @asynccontextmanager
    async def factory():
        yield session

    async def exercise():
        encoder = FixtureEncoder()
        fixture = QualityFixture(load_reference())
        await fixture.seed(factory, get_settings(), encoder, await encoder.identity())
        models = [call.args[0] for call in session.add.call_args_list]
        assert len([m for m in models if isinstance(m, DocumentEmbedding)]) == 13
        assert len([m for m in models if isinstance(m, DocumentEmbeddingJob)]) == 13
        assert all(m.status == "succeeded" and m.model_digest == "f" * 64 for m in models if isinstance(m, DocumentEmbeddingJob))
        assert any(m.position == 1 and m.start_offset > 0 for m in models if isinstance(m, DocumentChunk))
        assert len(fixture.candidates) == 25 and len(fixture.witnesses) == 24
        assert fixture.token not in repr(fixture)
        await fixture.cleanup(factory)
        statements = [call.args[0].compile(dialect=postgresql.dialect()) for call in session.execute.call_args_list]
        assert len(statements) == 6
        assert all("WHERE" in str(sql) and "LIKE" not in str(sql) for sql in statements)
        vectors = await encoder.encode(("Python PostgreSQL", "Python PostgreSQL"), await encoder.identity())
        assert vectors[0] == vectors[1] and math.hypot(*vectors[0]) == pytest.approx(1)
    asyncio.run(exercise())
