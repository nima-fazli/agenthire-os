import argparse
import os
import re
import secrets
import shlex
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from scripts.ci_execution import execute_plan, summary
from scripts.ci_plan import (
    cleanup_step,
    compose_prefix,
    new_project_name,
    repository_root,
    validate_project_name,
    verification_plan,
)


def require_compose_version(value: str) -> None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+]\S+)?", value.strip())
    if not match or tuple(map(int, match.groups())) < (2, 24, 4):
        raise ValueError("Docker Compose 2.24.4 or newer is required.")


def isolated_environment(
    original: Mapping[str, str],
    project: str,
    env_file: Path,
) -> dict[str, str]:
    validate_project_name(project)
    environment = {
        key: value
        for key, value in original.items()
        if not key.upper().startswith(("AGENTHIRE_", "COMPOSE_"))
    }
    environment.update(
        {
            "AGENTHIRE_CI_PROJECT": project,
            "AGENTHIRE_CI_ENV_FILE": env_file.as_posix(),
            "AGENTHIRE_POSTGRES_DB": "agenthire_ci",
            "AGENTHIRE_POSTGRES_USER": "agenthire_ci",
            "AGENTHIRE_POSTGRES_PASSWORD": secrets.token_hex(24),
            "AGENTHIRE_JWT_SECRET": secrets.token_hex(32),
            "AGENTHIRE_ENVIRONMENT": "test",
            "AGENTHIRE_DEBUG": "false",
            "AGENTHIRE_LOG_LEVEL": "INFO",
        }
    )
    return environment


def write_environment(path: Path, environment: Mapping[str, str]) -> None:
    keys = (
        "AGENTHIRE_POSTGRES_DB",
        "AGENTHIRE_POSTGRES_USER",
        "AGENTHIRE_POSTGRES_PASSWORD",
        "AGENTHIRE_JWT_SECRET",
        "AGENTHIRE_ENVIRONMENT",
        "AGENTHIRE_DEBUG",
        "AGENTHIRE_LOG_LEVEL",
    )
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(f"{key}={environment[key]}" for key in keys) + "\n")
    path.chmod(0o600)


def preflight(
    project: str,
    *,
    root: Path,
    environment: Mapping[str, str],
    runner: Callable = subprocess.run,
) -> None:
    validate_project_name(project)
    options = {
        "cwd": root,
        "env": dict(environment),
        "check": False,
        "timeout": 30,
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
    }
    version = runner(("docker", "compose", "version", "--short"), **options)
    if version.returncode:
        raise ValueError("Docker Compose is unavailable.")
    require_compose_version(version.stdout)
    for resource in ("container", "volume", "network"):
        command = ("docker", resource, "ls")
        if resource == "container":
            command += ("--all",)
        command += (
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            "{{.ID}}" if resource == "container" else "{{.Name}}",
        )
        result = runner(command, **options)
        if result.returncode:
            raise ValueError("Docker engine is unavailable.")
        if result.stdout.strip():
            raise ValueError("CI project already owns resources; refusing to reuse it.")


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Callable = subprocess.run,
) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a fresh isolated Docker stack."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the plan only.")
    args = parser.parse_args(argv)
    try:
        root = repository_root(Path.cwd())
        project = new_project_name()
        if args.dry_run:
            prefix = compose_prefix(root, project, root / "CI_ENV_CREATED_AT_RUNTIME")
            for step in (*verification_plan(prefix), cleanup_step(prefix)):
                print(f"{step.name}: {shlex.join(step.command)}", flush=True)
            print("[plan] No commands executed; no environment file created.")
            return 0
        with tempfile.TemporaryDirectory(prefix="agenthire-ci-") as directory:
            env_file = Path(directory).resolve() / "ci.env"
            environment = isolated_environment(os.environ, project, env_file)
            preflight(project, root=root, environment=environment, runner=runner)
            print(f"[ci] Temporary project: {project}", flush=True)
            write_environment(env_file, environment)
            prefix = compose_prefix(root, project, env_file)
            code, results = execute_plan(
                verification_plan(prefix),
                cleanup_step(prefix),
                root=root,
                environment=environment,
                runner=runner,
                log=lambda message: print(message, flush=True),
            )
            report = summary(results, passed=code == 0)
            print(report, flush=True)
            if os.environ.get("GITHUB_ACTIONS") == "true":
                destination = os.environ.get("GITHUB_STEP_SUMMARY")
                if destination:
                    try:
                        with Path(destination).open("a", encoding="utf-8") as handle:
                            handle.write(report)
                    except OSError:
                        print("[failed] Could not write the CI summary.")
                        return code or 2
            if code == 0:
                print("[success] Isolated Docker verification passed and cleaned up.")
            return code
    except KeyboardInterrupt:
        print("[failed] Verification interrupted.")
        return 130
    except (OSError, ValueError, subprocess.SubprocessError):
        print("[failed] CI setup failed. Check Docker Compose and the checkout.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
