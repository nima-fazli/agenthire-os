from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import ci_verify
from scripts.ci_plan import SMOKE_MODULES, UI_ASSETS

PROJECT = "agenthire-ci-" + "b" * 32


@pytest.fixture(autouse=True)
def complete_checkout(tmp_path, monkeypatch):
    for name in (
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
        ".github/workflows/verify.yml",
        ".github/dependabot.yml",
        "tests/recruiter_ui.test.mjs",
        "tests/recruiter_notifications.test.mjs",
        *(f"scripts/{name}.py" for name in SMOKE_MODULES),
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="agenthire-os"\n', encoding="utf-8"
    )
    (tmp_path / ".env").write_text("host-environment-preserved", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    yield
    assert (tmp_path / ".env").read_text() == "host-environment-preserved"


@pytest.mark.parametrize("value", ["2.24.4", "v2.40.1-desktop.1", "5.0.0"])
def test_supported_compose_versions(value):
    ci_verify.require_compose_version(value)


@pytest.mark.parametrize("value", ["2.24.3", "1.29.2", "garbage", "2.24", ""])
def test_unsupported_compose_versions(value):
    with pytest.raises(ValueError):
        ci_verify.require_compose_version(value)


def test_environment_is_fresh_and_does_not_mutate_host(tmp_path):
    original = {
        "PATH": "keep",
        "AGENTHIRE_POSTGRES_PASSWORD": "host-private",
        "AGENTHIRE_APP_NAME": "host-name",
        "AGENTHIRE_SEMANTIC_ENABLED": "true",
        "AGENTHIRE_EMBEDDING_BASE_URL": "http://foreign.invalid:11434",
        "COMPOSE_FILE": "foreign.yaml",
        "compose_project_name": "main",
        "DOCKER_CONTEXT": "desktop-linux",
    }
    first = ci_verify.isolated_environment(original, PROJECT, tmp_path / "ci.env")
    second = ci_verify.isolated_environment(original, PROJECT, tmp_path / "ci.env")
    assert original["AGENTHIRE_POSTGRES_PASSWORD"] == "host-private"
    assert first["DOCKER_CONTEXT"] == "desktop-linux"
    assert first["PATH"] == "keep"
    assert "AGENTHIRE_APP_NAME" not in first and "COMPOSE_FILE" not in first
    assert "compose_project_name" not in first
    assert "AGENTHIRE_SEMANTIC_ENABLED" not in first
    assert "AGENTHIRE_EMBEDDING_BASE_URL" not in first
    assert first["AGENTHIRE_ENVIRONMENT"] == "test"
    assert len(first["AGENTHIRE_JWT_SECRET"]) == 64
    assert first["AGENTHIRE_JWT_SECRET"] != second["AGENTHIRE_JWT_SECRET"]
    assert first["AGENTHIRE_POSTGRES_PASSWORD"] != second["AGENTHIRE_POSTGRES_PASSWORD"]


def test_environment_file_cannot_overwrite_existing_file(tmp_path):
    path = tmp_path / "ci.env"
    path.write_text("preserve", encoding="utf-8")
    environment = ci_verify.isolated_environment({}, PROJECT, path)
    with pytest.raises(FileExistsError):
        ci_verify.write_environment(path, environment)
    assert path.read_text() == "preserve"


def test_environment_file_contains_only_necessary_test_settings(tmp_path):
    path = tmp_path / "ci.env"
    environment = ci_verify.isolated_environment(
        {"OTHER_SECRET": "private"}, PROJECT, path
    )
    ci_verify.write_environment(path, environment)
    text = path.read_text()
    assert "OTHER_SECRET" not in text
    assert "AGENTHIRE_CI_ENV_FILE" not in text
    assert len(text.splitlines()) == 7


@pytest.mark.parametrize("occupied", ["container", "volume", "network"])
def test_existing_resources_are_never_reused_or_cleaned(occupied, tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        stdout = "2.40.1" if "version" in command else ""
        if command[1] == occupied:
            stdout = "existing-resource"
        return SimpleNamespace(returncode=0, stdout=stdout)

    with pytest.raises(ValueError, match="refusing"):
        ci_verify.preflight(PROJECT, root=tmp_path, environment={}, runner=run)
    assert not any("down" in command or "build" in command for command in calls)


def test_dry_run_has_no_process_or_file_side_effects(monkeypatch, capsys):
    before = set(Path.cwd().iterdir())

    def run(*args, **kwargs):
        pytest.fail("dry run must not launch a process")

    assert ci_verify.main(["--dry-run"], runner=run) == 0
    output = capsys.readouterr().out
    assert "No commands executed" in output
    assert set(Path.cwd().iterdir()) == before
    assert all(f"scripts.{name}" in output for name in SMOKE_MODULES)
    assert "scripts.semantic_retrieval_smoke" in output
    assert "scripts.recruiter_ui_smoke" in output
    assert "scripts.operations_smoke" in output
    assert "tests/recruiter_ui.test.mjs" in output
    assert "--volumes" in output


@pytest.mark.parametrize(
    "failure",
    [None, "docker-pytest", "docker-ui-tests", "retrieval_evaluation_smoke", "cleanup"],
    ids=["pass", "tests", "ui", "quality", "cleanup"],
)
def test_full_cli_preserves_isolation_failure_and_temporary_cleanup(
    failure, monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("AGENTHIRE_POSTGRES_PASSWORD", "host-private-password")
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "agenthire-os")
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    monkeypatch.setattr(ci_verify, "new_project_name", lambda: PROJECT)
    calls = []
    temporary = []

    def run(command, **options):
        calls.append(command)
        environment = options["env"]
        assert "COMPOSE_PROJECT_NAME" not in environment
        assert environment["AGENTHIRE_POSTGRES_PASSWORD"] != "host-private-password"
        if "capture_output" in options:
            return SimpleNamespace(
                returncode=0, stdout="2.40.1" if "version" in command else ""
            )
        assert command[command.index("--project-name") + 1] == PROJECT
        env_file = Path(command[command.index("--env-file") + 1])
        assert env_file.is_file()
        temporary.append(env_file)
        is_failed = (
            failure == "docker-pytest"
            and "pytest" in command
            or failure == "docker-ui-tests"
            and "node" in command
            or failure == "retrieval_evaluation_smoke"
            and command[-1] == "scripts.retrieval_evaluation_smoke"
            or failure == "cleanup"
            and "down" in command
        )
        return SimpleNamespace(returncode=9 if is_failed else 0)

    code = ci_verify.main([], runner=run)
    output = capsys.readouterr().out
    assert code == (9 if failure else 0)
    assert ("[success]" in output) == (failure is None)
    assert "host-private-password" not in output
    assert "down" in calls[-1]
    assert all(not path.exists() for path in temporary)
    if failure in {"docker-pytest", "docker-ui-tests"}:
        assert not any("up" in command for command in calls)
    if failure is None:
        assert sum(command[-1].startswith("scripts.") for command in calls) == len(SMOKE_MODULES)


def test_unavailable_docker_returns_safe_setup_failure(monkeypatch, capsys):
    def run(*args, **kwargs):
        raise OSError("private-docker-detail")

    assert ci_verify.main([], runner=run) == 2
    output = capsys.readouterr().out
    assert "private-docker-detail" not in output
    assert "[success]" not in output
