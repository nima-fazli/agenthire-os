"""Evaluate inside the local Compose network; retain JSON before container cleanup."""

import argparse
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scripts.local_demo import COMPOSE, ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["replay", "live"], default="replay")
    parser.add_argument(
        "--kind", choices=["recruiter", "applicant"], default="recruiter"
    )
    parser.add_argument("--repeat", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not shutil.which("docker"):
        parser.error("Start Docker Desktop/Engine first.")
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    output = (
        args.output or ROOT / "reports" / f"agent-{args.kind}-{args.mode}-{suffix}.json"
    ).resolve()
    if output.exists() or output.suffix.lower() != ".json":
        parser.error("Choose a new .json path. Existing reports are retained.")
    output.parent.mkdir(parents=True, exist_ok=True)
    container = "agenthire-eval-" + uuid4().hex[:16]
    try:
        result = subprocess.run(
            [
                *COMPOSE,
                "run",
                "--name",
                container,
                "-T",
                "--build",
                "--no-deps",
                "smoke",
                "python",
                "-m",
                "scripts.agent_evaluation",
                "--mode",
                args.mode,
                "--kind",
                args.kind,
                "--repeat",
                str(args.repeat),
                "--output",
                "/tmp/agent-evaluation.json",
            ],
            cwd=ROOT,
            check=False,
            timeout=7200,
        )
        copied = subprocess.run(
            ["docker", "cp", container + ":/tmp/agent-evaluation.json", str(output)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            timeout=30,
        )
        if copied.returncode:
            print(
                "No completed report was available. Inspect the container/model error above."
            )
            return 1
        print("Retained evaluation report: " + str(output))
        return result.returncode
    finally:
        subprocess.run(
            ["docker", "rm", "--force", container],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )


if __name__ == "__main__":
    raise SystemExit(main())
