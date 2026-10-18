import shutil
import subprocess
from pathlib import Path


def test_recruiting_workflow_client_acceptance():
    node = shutil.which("node")
    assert node is not None, "Node.js is required for recruiter acceptance."
    result = subprocess.run(
        (node, "--test", "tests/recruiter_workflow.test.mjs"),
        cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
        capture_output=True, encoding="utf-8", timeout=60, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
