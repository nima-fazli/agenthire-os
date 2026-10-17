import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

UI_ASSETS = tuple(f"app/web/assets/{name}" for name in (
    "index.html", "styles.css", "app.mjs", "api.mjs", "dom.mjs", "session.mjs",
    "requests.mjs", "workspace.mjs", "profiles.mjs", "candidates.mjs", "evidence.mjs", "notifications.mjs",
))

OPERATIONS_FILES = (
    "app/core/operational_policy.py", "app/core/probe_metrics.py", "app/core/probe_transport.py",
    "scripts/operations_probe.py", "scripts/stack_diagnostics.py", "scripts/runtime_diagnostics.py",
    "app/core/benchmark_metrics.py", "app/core/resource_metrics.py", "scripts/benchmark_http.py",
    "scripts/workload_benchmark.py", "scripts/model_benchmark.py", "scripts/resource_watch.py",
    "scripts/queue_watch.py", "scripts/benchmark_run.py",
    "app/core/recovery_archive.py", "scripts/recovery_objects.py",
    "scripts/recovery_fixture.py", "scripts/recovery_drill.py",
)

SMOKE_MODULES = (
    "docker_smoke",
    "candidate_smoke",
    "application_smoke",
    "candidate_document_smoke",
    "document_extraction_smoke",
    "document_chunk_smoke",
    "document_search_smoke",
    "job_retrieval_smoke",
    "job_matching_smoke",
    "retrieval_evaluation_smoke",
    "storage_integrity_smoke",
    "document_embeddings_smoke",
    "semantic_retrieval_smoke",
    "grounded_explanations_smoke",
    "recruiter_ui_smoke",
    "operations_smoke",
    "operations_failure_smoke",
    "workload_smoke",
)


@dataclass(frozen=True)
class Step:
    name: str
    command: tuple[str, ...]
    timeout: float = 300


def repository_root(path: Path) -> Path:
    root = path.resolve()
    required = (
        "pyproject.toml",
        "uv.lock",
        "Dockerfile",
        "compose.yaml",
        "compose.ci.yaml",
        "alembic.ini",
        "app/main.py",
        "app/web/router.py",
        "app/web/__init__.py",
        *UI_ASSETS,
        *OPERATIONS_FILES,
        ".github/workflows/verify.yml",
        ".github/dependabot.yml",
        "tests/recruiter_ui.test.mjs",
        "tests/recruiter_notifications.test.mjs",
        *(f"scripts/{name}.py" for name in SMOKE_MODULES),
    )
    if not all((root / name).is_file() for name in required):
        raise ValueError("Run from the complete AgentHire OS checkout.")
    if any((root / name).is_symlink() or not (root / name).stat().st_size for name in UI_ASSETS):
        raise ValueError("Recruiter UI assets must be nonempty regular files.")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    if project.get("project", {}).get("name") != "agenthire-os":
        raise ValueError("This checkout is not AgentHire OS.")
    return root


def new_project_name() -> str:
    return f"agenthire-ci-{uuid4().hex}"


def validate_project_name(project: str) -> None:
    if not re.fullmatch(r"agenthire-ci-[0-9a-f]{32}", project):
        raise ValueError("CI requires its own generated Compose project name.")


def compose_prefix(root: Path, project: str, env_file: Path) -> tuple[str, ...]:
    validate_project_name(project)
    if not root.is_absolute() or not env_file.is_absolute():
        raise ValueError("CI paths must be absolute.")
    return (
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        str(env_file),
        "--file",
        str(root / "compose.yaml"),
        "--file",
        str(root / "compose.ci.yaml"),
    )


def verification_plan(prefix: tuple[str, ...]) -> tuple[Step, ...]:
    return (
        Step("compose-config", prefix + ("config", "--quiet"), 30),
        Step("postgres-image", prefix + ("pull", "postgres"), 600),
        Step("test-image", prefix + ("--profile", "test", "build", "test"), 900),
        Step(
            "docker-pytest",
            prefix
            + (
                "--profile",
                "test",
                "run",
                "--rm",
                "test",
                "pytest",
                "-rs",
            ),
        ),
        Step(
            "docker-ruff",
            prefix
            + (
                "--profile",
                "test",
                "run",
                "--rm",
                "test",
                "ruff",
                "check",
                ".",
            ),
        ),
        Step(
            "docker-ui-tests",
            prefix + ("--profile", "test", "run", "--rm", "test", "node", "--test", "tests/recruiter_ui.test.mjs", "tests/recruiter_notifications.test.mjs"),
        ),
        Step(
            "runtime-images",
            prefix
            + (
                "build",
                "api",
                "migrate",
                "extraction-worker",
            ),
            1200,
        ),
        Step("smoke-image", prefix + ("--profile", "smoke", "build", "smoke"), 600),
        Step(
            "healthy-stack",
            prefix
            + (
                "up",
                "--detach",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "180",
                "--scale",
                "extraction-worker=2",
                "api",
                "extraction-worker",
            ),
            360,
        ),
        Step(
            "migration-head",
            prefix
            + (
                "run",
                "--rm",
                "migrate",
                "alembic",
                "current",
            ),
        ),
        *(
            Step(f"extraction-worker-{index}-health", prefix + (
                "exec", "--index", str(index), "-T", "extraction-worker", "python", "-m",
                "app.workers.document_extraction", "--healthcheck",
            ), 30)
            for index in (1, 2)
        ),
        Step(
            "migration-drift",
            prefix
            + (
                "run",
                "--rm",
                "migrate",
                "alembic",
                "check",
            ),
        ),
        *(
            Step(
                name,
                prefix
                + (
                    "--profile",
                    "smoke",
                    "run",
                    "--rm",
                    "smoke",
                    "python",
                    "-m",
                    f"scripts.{name}",
                ),
            )
            for name in SMOKE_MODULES
        ),
        Step("recovery-drill", (sys.executable, "-m", "scripts.recovery_drill", "--execute"), 2400),
    )


def cleanup_step(prefix: tuple[str, ...]) -> Step:
    return Step(
        "cleanup-ci-stack",
        prefix
        + (
            "--profile",
            "test",
            "--profile",
            "smoke",
            "down",
            "--volumes",
            "--remove-orphans",
        ),
        240,
    )
