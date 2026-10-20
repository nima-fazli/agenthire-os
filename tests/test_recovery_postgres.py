import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts.ci_plan import compose_prefix
from scripts.ci_verify import isolated_environment
from scripts.recovery_postgres import (
    CATALOG_QUERY,
    RecoveryDatabaseFailure,
    require_empty_database,
)

PROJECT = "agenthire-ci-" + "a" * 32


class Clock:
    def __init__(self):
        self.now = 0

    def read(self):
        return self.now

    def pause(self, seconds):
        self.now += seconds


def check(tmp_path, runner, *, timeout=3, prefix=None, environment=None):
    path = tmp_path / "target.env"
    clock = Clock()
    prefix = compose_prefix(tmp_path, PROJECT, path) if prefix is None else prefix
    environment = isolated_environment({}, PROJECT, path) if environment is None else environment
    require_empty_database(tmp_path, prefix, environment, runner=runner,
                           timeout=timeout, clock=clock.read, pause=clock.pause)


def result(code=0, out=b"0\n", error=b"PRIVATE-ERROR"):
    return SimpleNamespace(returncode=code, stdout=out, stderr=error)


def test_socket_only_startup_cannot_reach_the_empty_catalog_gate(tmp_path):
    probes, calls = iter([2, 1, 0]), []

    def runner(command, **options):
        calls.append(command)
        assert command[:2] == ("docker", "compose")
        assert PROJECT in command and "-T" in command
        assert options["timeout"] <= 3 and options["stderr"] == subprocess.PIPE
        if "pg_isready" in command:
            assert "--host=127.0.0.1" in command and "--port=5432" in command
            return result(next(probes))
        assert len(calls) == 4 and "psql" in command
        assert "--command" not in command and "--file=-" in command
        assert "--set=ON_ERROR_STOP=1" in command
        assert "--set=VERBOSITY=sqlstate" in command
        assert isinstance(options["stdin"].read(), bytes)
        options["stdin"].seek(0)
        assert options["stdin"].read() == CATALOG_QUERY
        assert not any("SELECT" in word or "public" in word for word in command)
        return result()

    check(tmp_path, runner)


def test_catalog_query_reaches_a_child_process_as_exact_bytes(tmp_path):
    def runner(command, **options):
        if "pg_isready" in command:
            return result()
        # Exercise the same binary stdin transfer on the executing operating system.
        import sys
        child = subprocess.run([sys.executable, "-c",
            "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
            stdin=options["stdin"], capture_output=True, check=True, timeout=5)
        assert child.stdout == CATALOG_QUERY
        return result()

    check(tmp_path, runner)


@pytest.mark.parametrize("value", [b"1\n", b"20\n"])
def test_a_nonempty_destination_is_never_accepted(tmp_path, value):
    def runner(command, **options):
        return result(out=value) if "psql" in command else result()

    with pytest.raises(RecoveryDatabaseFailure, match="destination_not_empty"):
        check(tmp_path, runner)


@pytest.mark.parametrize("value", [b"", b"PRIVATE", b"0\n1\n", b"-1", b"\xff", b"0" * 21])
def test_invalid_catalog_output_fails_closed(tmp_path, value):
    def runner(command, **options):
        return result(out=value) if "psql" in command else result()

    with pytest.raises(RecoveryDatabaseFailure, match="catalog_invalid"):
        check(tmp_path, runner)


@pytest.mark.parametrize("exit_code,state", [(1, None), (2, None), (3, "42601"), (7, None)])
def test_query_failure_has_safe_codes_and_is_not_retried(tmp_path, exit_code, state):
    calls = []

    def runner(command, **options):
        calls.append(command)
        error = b"ERROR: 42601\nPRIVATE-ERROR" if state else b"PRIVATE-ERROR"
        return result(exit_code, error=error) if "psql" in command else result()

    with pytest.raises(RecoveryDatabaseFailure) as failure:
        check(tmp_path, runner)
    details = failure.value.details
    assert details == {"operation": "psql", "exit_code": exit_code, "sqlstate": state}
    assert str(failure.value) == ("recovery_database_connection_failed" if exit_code == 2
                                  else "recovery_database_query_failed")
    assert len(calls) == 2
    assert "PRIVATE" not in json.dumps(details) + str(failure.value)


def test_probe_deadline_never_runs_a_catalog_query(tmp_path):
    calls = []

    def runner(command, **options):
        calls.append(command)
        assert "pg_isready" in command
        return result(2)

    with pytest.raises(RecoveryDatabaseFailure, match="database_timeout"):
        check(tmp_path, runner)
    assert len(calls) == 3


def test_misconfigured_probe_fails_without_retrying(tmp_path):
    calls = []

    def runner(command, **options):
        calls.append(command)
        return result(3)

    with pytest.raises(RecoveryDatabaseFailure, match="probe_failed"):
        check(tmp_path, runner)
    assert len(calls) == 1


@pytest.mark.parametrize("error", [OSError("PRIVATE"), subprocess.TimeoutExpired("PRIVATE", 3)])
def test_process_failures_do_not_expose_private_text(tmp_path, error):
    def runner(*args, **kwargs):
        raise error

    with pytest.raises(RecoveryDatabaseFailure) as failure:
        check(tmp_path, runner)
    assert failure.value.details["operation"] == "pg_isready"
    assert "PRIVATE" not in str(failure.value) + json.dumps(failure.value.details)


@pytest.mark.parametrize("change", ["project", "database", "environment", "prefix", "timeout"])
def test_normal_or_unmatched_database_scope_is_refused_before_a_process(tmp_path, change):
    prefix = compose_prefix(tmp_path, PROJECT, tmp_path / "env")
    environment = isolated_environment({}, PROJECT, tmp_path / "env")
    timeout = 3
    if change == "project": environment["AGENTHIRE_CI_PROJECT"] = "agenthire-os"
    elif change == "database": environment["AGENTHIRE_POSTGRES_DB"] = "normal"
    elif change == "environment": environment["AGENTHIRE_ENVIRONMENT"] = "production"
    elif change == "prefix": prefix = ("docker", "compose", "--project-name")
    else: timeout = True
    with pytest.raises(ValueError):
        check(tmp_path, lambda *args, **kwargs: pytest.fail("unsafe scope reached Docker"),
              prefix=prefix, environment=environment, timeout=timeout)
