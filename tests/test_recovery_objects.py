import asyncio
import hashlib
import io
from types import SimpleNamespace

import pytest

from scripts import recovery_objects as objects

PROJECT = "agenthire-ci-" + "a" * 32


@pytest.mark.parametrize("changed", ["project", "environment", "database", "user", "host"])
def test_scope_guard_rejects_normal_or_foreign_stack(monkeypatch, changed):
    settings = SimpleNamespace(environment="test", postgres_db="agenthire_ci", postgres_user="agenthire_ci", postgres_host="postgres")
    monkeypatch.setattr(objects, "get_settings", lambda: settings)
    monkeypatch.setenv("AGENTHIRE_RECOVERY_PROJECT", PROJECT)
    if changed == "project":
        monkeypatch.setenv("AGENTHIRE_RECOVERY_PROJECT", "agenthire-ci-" + "b" * 32)
    else:
        field = {"database": "postgres_db", "user": "postgres_user", "host": "postgres_host"}.get(changed, changed)
        setattr(settings, field, "normal")
    with pytest.raises(ValueError):
        objects.require_scope(PROJECT)


@pytest.mark.parametrize("failure", [None, "pending", "schema", "version", "query"], ids=["pass", "pending", "schema", "version", "query"])
def test_catalog_uses_read_only_snapshot_and_always_closes(monkeypatch, failure):
    calls = []
    class Transaction:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
    class Database:
        def transaction(self, **kwargs):
            assert kwargs == {"isolation": "repeatable_read", "readonly": True}
            return Transaction()
        async def execute(self, query): calls.append(query)
        async def fetchval(self, query):
            return (190000 if failure == "version" else 180006) if "server_version_num" in query else int(failure == "pending")
        async def fetch(self, query):
            if "alembic_version" in query:
                return [{"version_num": "wrong" if failure == "schema" else "0017_access_sessions"}]
            if failure == "query":
                raise RuntimeError("private detail")
            assert "LIMIT 1001" in query
            return []
        async def close(self): calls.append("closed")
    async def connect(): return Database()
    monkeypatch.setattr(objects, "connection", connect)
    if failure:
        with pytest.raises((ValueError, RuntimeError)):
            asyncio.run(objects.read_catalog())
    else:
        assert asyncio.run(objects.read_catalog()) == []
    assert calls[-1] == "closed"


def test_export_stdout_contains_only_archive_and_errors_do_not_leak(monkeypatch, tmp_path, capsys):
    data = b"%PDF-1.7\nsynthetic\n%%EOF"
    key = "a" * 32 + ".pdf"
    (tmp_path / key).write_bytes(data)
    async def read(): return [{"key": key, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}]
    monkeypatch.setattr(objects, "require_scope", lambda project: SimpleNamespace(document_storage_path=tmp_path))
    monkeypatch.setattr(objects, "read_catalog", read)
    output = io.BytesIO()
    with monkeypatch.context() as patch:
        patch.setattr(objects.sys, "stdout", SimpleNamespace(buffer=output))
        assert objects.main(["export", "--project", PROJECT]) == 0
    assert output.getvalue().startswith(b"PK")
    async def failed(): raise RuntimeError("PRIVATE-CATALOG-DETAIL")
    monkeypatch.setattr(objects, "read_catalog", failed)
    assert objects.main(["verify", "--project", PROJECT]) == 1
    captured = capsys.readouterr()
    assert "PRIVATE-CATALOG-DETAIL" not in captured.out + captured.err
    assert "recovery_objects_unavailable" in captured.err
