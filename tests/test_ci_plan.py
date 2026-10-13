from pathlib import Path

import pytest

from scripts.ci_plan import (
    SMOKE_MODULES,
    cleanup_step,
    compose_prefix,
    new_project_name,
    repository_root,
    validate_project_name,
    verification_plan,
)

PROJECT = "agenthire-ci-" + "a" * 32


def make_checkout(root):
    for name in (
        "pyproject.toml",
        "uv.lock",
        "Dockerfile",
        "compose.yaml",
        "compose.ci.yaml",
        "alembic.ini",
        "app/main.py",
        *(f"scripts/{name}.py" for name in SMOKE_MODULES),
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    (root / "pyproject.toml").write_text(
        '[project]\nname="agenthire-os"\n', encoding="utf-8"
    )
    return root


def test_repository_root_accepts_complete_checkout(tmp_path):
    assert repository_root(make_checkout(tmp_path)) == tmp_path.resolve()


def test_foreign_project_is_rejected(tmp_path):
    root = make_checkout(tmp_path)
    (root / "pyproject.toml").write_text('[project]\nname="other"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="not AgentHire"):
        repository_root(root)


def test_incomplete_checkout_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="complete"):
        repository_root(tmp_path)


def test_project_names_are_unique_and_owned():
    projects = {new_project_name() for _ in range(20)}
    assert len(projects) == 20
    for project in projects:
        validate_project_name(project)


@pytest.mark.parametrize(
    "value",
    [
        "main",
        "agenthire-os",
        "agenthire-ci-",
        "agenthire-ci-../main",
        "agenthire-ci-" + "A" * 32,
        "agenthire-ci-" + "a" * 31,
        PROJECT + "\n",
        "--project-name=main",
    ],
    ids=[
        "main",
        "existing",
        "empty",
        "path",
        "uppercase",
        "short",
        "newline",
        "option",
    ],
)
def test_foreign_project_names_are_rejected(value):
    with pytest.raises(ValueError):
        validate_project_name(value)


def test_commands_keep_spaces_as_single_arguments(tmp_path):
    root = tmp_path / "checkout with spaces"
    env_file = tmp_path / "temporary directory" / "ci.env"
    prefix = compose_prefix(root, PROJECT, env_file)
    steps = verification_plan(prefix)
    assert len(steps) == 10 + len(SMOKE_MODULES)
    assert SMOKE_MODULES[-2:] == ("storage_integrity_smoke", "document_embeddings_smoke")
    for step in (*steps, cleanup_step(prefix)):
        assert step.command[: len(prefix)] == prefix
        assert step.command[step.command.index("--project-name") + 1] == PROJECT
        assert str(root / "compose.ci.yaml") in step.command
        assert str(env_file) in step.command
    up = next(step for step in steps if step.name == "healthy-stack")
    assert "extraction-worker=2" in up.command
    modules = [step.command[-1] for step in steps if step.name in SMOKE_MODULES]
    assert modules == [f"scripts.{name}" for name in SMOKE_MODULES]


@pytest.mark.parametrize(
    "root,env_file",
    [
        (Path("relative"), Path("/tmp/ci.env")),
        (Path("/tmp/repo"), Path("relative.env")),
    ],
    ids=["root", "environment"],
)
def test_relative_paths_cannot_reach_compose(root, env_file):
    with pytest.raises(ValueError, match="absolute"):
        compose_prefix(root, PROJECT, env_file)
