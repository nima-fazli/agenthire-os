import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.recovery_archive import export_objects
from scripts import recovery_drill as drill
from scripts.recovery_postgres import CATALOG_QUERY
from tests.test_recovery_archive import objects

SOURCE = "agenthire-ci-" + "a" * 32
TARGET = "agenthire-ci-" + "b" * 32


class Runner:
    def __init__(self, archive, failure=None):
        self.archive, self.failure, self.calls = archive, failure, []

    def __call__(self, command, **options):
        self.calls.append(tuple(command))
        if command[:3] == ("docker", "compose", "version"):
            return SimpleNamespace(returncode=0, stdout="5.5.1")
        if command[1] in {"container", "volume", "network"}:
            occupied = self.failure == "occupied" and TARGET in command[-3]
            return SimpleNamespace(returncode=0, stdout="existing" if occupied else "")
        assert "--project-name" in command
        project = command[command.index("--project-name") + 1]
        assert project in {SOURCE, TARGET}
        assert options["env"]["AGENTHIRE_POSTGRES_PASSWORD"] != "HOST-PRIVATE"
        env_file = Path(command[command.index("--env-file") + 1])
        assert env_file.is_file()
        if self.failure == "timeout" and "pg_dump" in command and "--version" not in command:
            raise subprocess.TimeoutExpired(command, 1)
        failed = (self.failure == "build" and "build" in command or
                  self.failure == "restore" and "pg_restore" in command and "--version" not in command or
                  self.failure == "cleanup" and "down" in command)
        if failed:
            return SimpleNamespace(returncode=7, stdout=b"PRIVATE-OUTPUT", stderr=b"PRIVATE-ERROR")
        if (self.failure == "probe" and "pg_isready" in command
                or self.failure == "query" and "psql" in command):
            return SimpleNamespace(returncode=3, stdout=b"PRIVATE-OUTPUT", stderr=b"ERROR: 42601\nPRIVATE-ERROR")
        value = b""
        if "--version" in command:
            value = b"pg_dump (PostgreSQL) 18.6\n"
        elif "ps" in command:
            value = b"still-running" if self.failure == "writers" else b""
        elif "psql" in command:
            assert options["stdin"].read() == CATALOG_QUERY
            assert "--command" not in command and "--file=-" in command
            value = b"1\n" if self.failure == "target" else b"0\n"
        elif "pg_dump" in command:
            options["stdout"].write(b"PGDMP-synthetic-archive")
        elif "pg_restore" in command:
            assert options["stdin"].read() == b"PGDMP-synthetic-archive"
            assert "--single-transaction" in command and "--exit-on-error" in command
            assert "--clean" not in command and "--create" not in command
        elif "scripts.recovery_objects" in command:
            if "export" in command:
                options["stdout"].write(self.archive)
            else:
                if "import" in command:
                    assert options["stdin"].read() == self.archive
                value = json.dumps({"status": "passed", "objects": 2, "database_catalog_matches": True}).encode()
        elif "scripts.recovery_fixture" in command:
            value = json.dumps({"status": "passed", "documents": 2, "organizations": 2,
                                "pdf_downloads_verified": 2, "lexical_retrievals_verified": 2,
                                "tenant_isolation_verified": self.failure != "api",
                                "embedding_vectors_verified": 2}).encode()
        elif "alembic" in command and "current" in command:
            value = b"0018_local_agents (head)\n"
        return SimpleNamespace(returncode=0, stdout=value, stderr=b"")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    source = tmp_path / "objects"
    source.mkdir()
    data = io.BytesIO()
    export_objects(source, objects(source), data)
    projects = iter([SOURCE, TARGET])
    monkeypatch.setattr(drill, "new_project_name", lambda: next(projects))
    monkeypatch.setattr(drill, "repository_root", lambda path: tmp_path)
    monkeypatch.setenv("AGENTHIRE_POSTGRES_PASSWORD", "HOST-PRIVATE")
    (tmp_path / ".env").write_text("PRESERVE")
    return tmp_path, data.getvalue()


def test_plan_has_no_process_or_file_side_effects(setup, capsys):
    root, _archive = setup
    before = set(root.iterdir())
    def run(*args, **kwargs): pytest.fail("plan launched a process")
    assert drill.main([], runner=run) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "plan"
    assert set(root.iterdir()) == before


@pytest.mark.parametrize("failure", [None, "occupied", "build", "writers", "target", "restore", "api", "cleanup", "timeout",
                                    "probe", "query"])
def test_owned_lifecycle_failure_and_cleanup_boundaries(setup, failure, capsys):
    root, archive = setup
    runner = Runner(archive, failure)
    code = drill.main(["--execute"], runner=runner)
    text = capsys.readouterr().out
    report = json.loads(text.splitlines()[-1])
    assert code == (0 if failure is None else 1)
    assert report["status"] == ("passed" if failure is None else "failed")
    assert "HOST-PRIVATE" not in text and "PRIVATE-OUTPUT" not in text and "PRIVATE-ERROR" not in text
    assert (root / ".env").read_text() == "PRESERVE"
    cleanup = [command for command in runner.calls if "down" in command]
    if failure == "occupied":
        assert not cleanup and not any("build" in command for command in runner.calls)
    else:
        assert len(cleanup) == 2 and all("--volumes" in command for command in cleanup)
    if failure in {"writers", "target", "build", "occupied", "probe", "query"}:
        assert not any("pg_restore" in command and "--version" not in command for command in runner.calls)
    if failure is None:
        stopped = next(i for i, command in enumerate(runner.calls) if "stop" in command)
        dumped = next(i for i, command in enumerate(runner.calls) if "pg_dump" in command and "--version" not in command)
        assert stopped < dumped
        verified = next(i for i, command in enumerate(runner.calls) if "scripts.recovery_objects" in command and "verify" in command)
        target_up = next(i for i, command in enumerate(runner.calls) if TARGET in command and "up" in command and "api" in command)
        assert verified < target_up
        assert report["cleanup"] == "completed" and report["document_integrity_verified"] is True
        assert report["normal_stack_touched"] is False and report["retained_backup"] is False
        assert report["target_database_check"] == "passed"
        probes = [i for i, command in enumerate(runner.calls) if "pg_isready" in command]
        catalog = next(i for i, command in enumerate(runner.calls) if "psql" in command)
        assert len(probes) == 1 and probes[0] < catalog
    if failure in {"probe", "query"}:
        assert report["diagnostic"] == ("recovery_database_probe_failed" if failure == "probe"
                                         else "recovery_database_query_failed")
        assert report["database_failure"]["exit_code"] == 3
        assert report["last_operation"] == ("pg_isready" if failure == "probe" else "psql")
        assert report["cleanup"] == "completed"
    if failure == "cleanup":
        assert report["cleanup"] == "attention" and report["diagnostic"] == "recovery_cleanup_failed"


def test_bundle_corruption_stops_before_restore(setup, monkeypatch, capsys):
    _root, archive = setup
    original = drill.verify_bundle
    def corrupt(directory, expected):
        (directory / "database.dump").write_bytes(b"corrupted")
        original(directory, expected)
    monkeypatch.setattr(drill, "verify_bundle", corrupt)
    runner = Runner(archive)
    assert drill.main(["--execute"], runner=runner) == 1
    assert not any("pg_restore" in command for command in runner.calls)
    assert len([command for command in runner.calls if "down" in command]) == 2
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["status"] == "failed"


def test_cleanup_failure_keeps_priority_over_the_catalog_query_failure(setup, capsys):
    _root, archive = setup
    original = Runner(archive, "query")

    def runner(command, **options):
        value = original(command, **options)
        return SimpleNamespace(returncode=7, stdout=b"PRIVATE", stderr=b"PRIVATE") if "down" in command else value

    assert drill.main(["--execute"], runner=runner) == 1
    text = capsys.readouterr().out
    report = json.loads(text.splitlines()[-1])
    assert report["cleanup"] == "attention" and report["diagnostic"] == "recovery_cleanup_failed"
    assert report["database_failure"]["sqlstate"] == "42601"
    assert "PRIVATE" not in text
