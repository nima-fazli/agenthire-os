"""Keep client error regressions inside the normal Python/CI acceptance gate."""

import shutil
import subprocess
from pathlib import Path


def test_localized_client_error_contracts():
    node = shutil.which("node")
    assert node is not None, "Node.js is required for recruiter client acceptance."
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        (node, "--test", "tests/recruiter_api_errors.test.mjs"),
        cwd=root, stdin=subprocess.DEVNULL, capture_output=True,
        encoding="utf-8", timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
