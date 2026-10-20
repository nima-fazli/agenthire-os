import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ai_quality_acceptance import load_manifest
from scripts.ci_plan import repository_root


def copy_test_context(root, destination):
    """Materialize the local COPY inputs used by foundation and test, without Docker."""
    stage = None
    for raw in (root / "Dockerfile").read_text(encoding="utf-8").splitlines():
        if not raw.startswith(("FROM ", "COPY ")):
            continue
        words = shlex.split(raw)
        if not words:
            continue
        if words[0] == "FROM":
            stage = words[-1]
        if stage not in {"foundation", "test"} or words[0] != "COPY" or any(w.startswith("--from=") for w in words):
            continue
        arguments = [w for w in words[1:] if not w.startswith("--")]
        for source in arguments[:-1]:
            origin = root / source
            target = destination / arguments[-1]
            if len(arguments) > 2 or arguments[-1].endswith("/"):
                target /= origin.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if origin.is_dir():
                shutil.copytree(origin, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), dirs_exist_ok=True)
            else:
                shutil.copyfile(origin, target)


@pytest.fixture
def context(tmp_path):
    root = Path(__file__).resolve().parents[1]
    copy_test_context(root, tmp_path)
    return tmp_path


def test_test_image_inputs_include_all_acceptance_sources(context):
    assert repository_root(context) == context
    assert load_manifest(context)["base_commit"] == "261dd607b740a8d91d0bafabe2cb268c276c1c75"
    assert not (context / ".env").exists() and not (context / ".git").exists()


def test_missing_readme_is_a_packaging_failure_not_a_skipped_check(context):
    (context / "README.md").unlink()
    with pytest.raises(ValueError, match="missing_quality_source: README.md"):
        load_manifest(context)


def test_the_three_reported_docker_failures_pass_with_test_copy_inputs(context):
    environment = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "tests/test_ai_quality_acceptance.py::test_delivered_manifest_is_complete_and_detects_modified_code",
        "tests/test_ai_quality_acceptance.py::test_acceptance_plan_has_no_mutation_or_commits",
        "tests/test_ai_quality_run.py::test_default_is_plan_and_preflight_collision_never_cleans"],
        cwd=context, env=environment, capture_output=True, text=True, timeout=90, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
