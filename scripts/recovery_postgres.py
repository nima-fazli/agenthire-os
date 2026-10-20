"""Read-only readiness and empty-catalog gates for a fresh isolated restore target."""

import re
import subprocess
import tempfile
import time

from scripts.ci_plan import validate_project_name

CATALOG_QUERY = b"SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public';\n"


class RecoveryDatabaseFailure(ValueError):
    def __init__(self, code, operation, exit_code=None, sqlstate=None):
        super().__init__(code)
        self.details = {"operation": operation, "exit_code": exit_code, "sqlstate": sqlstate}


def require_empty_database(root, prefix, environment, *, runner=subprocess.run,
                           timeout=90, clock=time.monotonic, pause=time.sleep):
    """Wait for final TCP startup, then inspect public tables without shell SQL arguments."""
    prefix = tuple(prefix)
    project = environment.get("AGENTHIRE_CI_PROJECT", "")
    validate_project_name(project)
    if (prefix[:2] != ("docker", "compose") or prefix.count("--project-name") != 1
            or prefix.index("--project-name") + 1 >= len(prefix)
            or prefix[prefix.index("--project-name") + 1] != project
            or environment.get("AGENTHIRE_ENVIRONMENT") != "test"
            or environment.get("AGENTHIRE_POSTGRES_DB") != "agenthire_ci"
            or environment.get("AGENTHIRE_POSTGRES_USER") != "agenthire_ci"
            or type(timeout) is not int or not 1 <= timeout <= 120):
        raise ValueError("isolated_restore_database_required")
    deadline = clock() + timeout
    pg = (*prefix, "exec", "-T", "postgres")

    def call(operation, arguments, *, input_file=None):
        remaining = deadline - clock()
        if remaining <= 0:
            raise RecoveryDatabaseFailure("recovery_database_timeout", operation)
        try:
            return runner((*pg, operation, *arguments), cwd=root, env=environment, check=False,
                          stdin=subprocess.DEVNULL if input_file is None else input_file,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=min(30, remaining))
        except subprocess.TimeoutExpired:
            raise RecoveryDatabaseFailure("recovery_database_timeout", operation) from None
        except (OSError, subprocess.SubprocessError):
            raise RecoveryDatabaseFailure("recovery_database_process_failed", operation) from None

    # The image's initialization server accepts Unix sockets before final TCP startup.
    while True:
        result = call("pg_isready", ("--host=127.0.0.1", "--port=5432", "--timeout=2", "--quiet",
                                     "--username=agenthire_ci", "--dbname=agenthire_ci"))
        if result.returncode == 0:
            break
        if result.returncode not in {1, 2}:
            raise RecoveryDatabaseFailure("recovery_database_probe_failed", "pg_isready", result.returncode)
        remaining = deadline - clock()
        if remaining <= 0:
            raise RecoveryDatabaseFailure("recovery_database_timeout", "pg_isready", result.returncode)
        pause(min(1, remaining))

    # Binary stdin preserves quotes through Python, Windows, Docker CLI, and Compose.
    with tempfile.TemporaryFile() as query:
        query.write(CATALOG_QUERY)
        query.seek(0)
        result = call("psql", ("--no-psqlrc", "--no-password", "--tuples-only", "--no-align",
                               "--set=ON_ERROR_STOP=1", "--set=VERBOSITY=sqlstate",
                               "--username=agenthire_ci", "--dbname=agenthire_ci", "--file=-"),
                      input_file=query)
    if result.returncode:
        error = result.stderr or b""
        error = error[:4096].decode("utf-8", errors="replace") if isinstance(error, bytes) else error[:4096]
        state = re.search(r"\b(?:ERROR|FATAL):\s+([0-9A-Z]{5})(?:\s|$)", error)
        code = "recovery_database_connection_failed" if result.returncode == 2 else "recovery_database_query_failed"
        raise RecoveryDatabaseFailure(code, "psql", result.returncode, state.group(1) if state else None)
    value = result.stdout
    value = value.decode("ascii", errors="replace") if isinstance(value, bytes) else value
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,20}", value.strip()):
        raise RecoveryDatabaseFailure("recovery_database_catalog_invalid", "psql", 0)
    if int(value.strip()) != 0:
        raise RecoveryDatabaseFailure("recovery_destination_not_empty", "psql", 0)
