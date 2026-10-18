import asyncio
import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from scripts import backup_objects as module
from scripts import recovery_objects


def settings(**updates):
    values = {"environment": "local", "postgres_host": "postgres", "postgres_port": 5432,
              "postgres_db": "agenthire", "postgres_user": "agenthire",
              "postgres_password": SecretStr("PRIVATE-DB"), "jwt_secret": SecretStr("PRIVATE-JWT")}
    return SimpleNamespace(**(values | updates))


def test_normal_helper_is_read_only_and_requires_explicit_scope(monkeypatch):
    monkeypatch.setattr(module, "get_settings", settings)
    with pytest.raises(ValueError, match="scope"):
        module.authorize("agenthire-os", "audit")
    monkeypatch.setenv("AGENTHIRE_BACKUP_PROJECT", "agenthire-os")
    assert module.authorize("agenthire-os", "export").postgres_db == "agenthire"
    with pytest.raises(ValueError, match="reading"):
        module.authorize("agenthire-os", "import")
    monkeypatch.setattr(module, "get_settings", lambda: settings(environment="test"))
    with pytest.raises(ValueError):
        module.authorize("agenthire-os", "audit")


def test_isolated_helper_requires_both_markers_and_ci_database(monkeypatch):
    project = "agenthire-ci-" + "a" * 32
    monkeypatch.setenv("AGENTHIRE_BACKUP_PROJECT", project)
    monkeypatch.setattr(recovery_objects, "get_settings", lambda: settings(
        environment="test", postgres_db="agenthire_ci", postgres_user="agenthire_ci"))
    with pytest.raises(ValueError):
        module.authorize(project, "import")
    monkeypatch.setenv("AGENTHIRE_RECOVERY_PROJECT", project)
    assert module.authorize(project, "import").environment == "test"


class Database:
    def __init__(self):
        self.values = ["first-private-row", "second-private-row"]
        self.size, self.sequence, self.closed = 10000, 17, False
        self.names = [{"name": "organizations", "kind": "r"}, {"name": "test_seq", "kind": "S"}]
        self.commands = []

    @asynccontextmanager
    async def transaction(self, **options):
        assert options == {"isolation": "repeatable_read", "readonly": True}
        yield

    async def execute(self, command):
        self.commands.append(command)
        assert command.startswith("SET LOCAL")

    async def fetchval(self, command):
        return self.size if "pg_database_size" in command else "0.8.6"

    async def fetch(self, command):
        return self.names

    async def fetchrow(self, command):
        assert command == 'SELECT last_value, is_called FROM public."test_seq"'
        return {"last_value": self.sequence, "is_called": True}

    async def cursor(self, query, **options):
        assert "sha256(convert_to(to_jsonb(t)::text" in query
        assert query.endswith('FROM public."organizations" AS t')
        for value in (hashlib.sha256(value.encode()).hexdigest() for value in self.values):
            yield {"digest": value}

    async def close(self):
        self.closed = True


def test_database_fingerprint_tracks_rows_sequences_and_ignores_physical_size(monkeypatch):
    database = Database()
    async def connect(): return database
    async def catalog(): return []
    monkeypatch.setattr(module, "connection", connect)
    monkeypatch.setattr(module, "read_catalog", catalog)
    first = asyncio.run(module.database_audit())
    database.values.reverse()
    database.size *= 2
    second = asyncio.run(module.database_audit())
    assert first["fingerprint"] == second["fingerprint"]
    database.sequence += 1
    assert asyncio.run(module.database_audit())["fingerprint"] != first["fingerprint"]
    database.sequence -= 1
    database.values[0] = "changed-private-row"
    assert asyncio.run(module.database_audit())["fingerprint"] != first["fingerprint"]
    assert database.closed and first["rows"] == 2
    assert "private-row" not in str(first)


@pytest.mark.parametrize("failure", ["name", "size", "relations"])
def test_database_budgets_and_unsafe_identifiers_fail_closed(monkeypatch, failure):
    database = Database()
    if failure == "name": database.names[0]["name"] = 'private";DROP TABLE users'
    elif failure == "size": database.size = 257 * 1024**2
    else: database.names *= 100
    async def connect(): return database
    async def catalog(): return []
    monkeypatch.setattr(module, "connection", connect)
    monkeypatch.setattr(module, "read_catalog", catalog)
    with pytest.raises(ValueError):
        asyncio.run(module.database_audit())
    assert database.closed


def test_helper_failure_does_not_expose_exception_or_credentials(monkeypatch, capsys):
    monkeypatch.setattr(module, "authorize", lambda *args: settings())
    async def audit(): raise RuntimeError("PRIVATE-DATABASE-DETAIL")
    monkeypatch.setattr(module, "database_audit", audit)
    assert module.main(["audit", "--project", "agenthire-os"]) == 1
    output = capsys.readouterr()
    assert "PRIVATE" not in output.out + output.err
    assert "backup_objects_unavailable" in output.err
