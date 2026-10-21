"""Standard-library launcher. Preserve existing environment and Docker volumes."""

import argparse
import secrets
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.agents.yaml"]


def ensure_environment(root=ROOT):
    path = root / ".env"
    if path.exists():
        return False
    body = (
        "AGENTHIRE_ENVIRONMENT=local\nAGENTHIRE_POSTGRES_DB=agenthire\nAGENTHIRE_POSTGRES_USER=agenthire\nAGENTHIRE_POSTGRES_PASSWORD="
        + secrets.token_urlsafe(32)
        + "\nAGENTHIRE_JWT_SECRET="
        + secrets.token_urlsafe(48)
        + "\nAGENTHIRE_API_PORT=8000\nAGENTHIRE_AGENT_MODEL=qwen3:4b\n"
    )
    with path.open("x", encoding="utf-8") as handle:
        handle.write(body)
    path.chmod(0o600)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args(argv)
    if not args.start and not args.seed:
        print(
            "Start: python -m scripts.local_demo --start --seed. Existing configuration and volumes are retained."
        )
        return 0
    if not shutil.which("docker"):
        parser.error("Start Docker Desktop/Engine before running the local stack.")
    ensure_environment()
    subprocess.run(["docker", "info"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    if args.start:
        subprocess.run(
            [*COMPOSE, "up", "-d", "--build", "--wait", "--wait-timeout", "240"],
            cwd=ROOT,
            check=True,
        )
    if args.seed:
        subprocess.run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "api",
                "python",
                "-m",
                "app.tools.demo_seed",
                "--execute",
                "--with-applications",
            ],
            cwd=ROOT,
            check=True,
        )
    print(
        "Agent Center: http://localhost:8000/agent-center/\nApplicant Portal: http://localhost:8000/portal/\nRecorded demo: http://localhost:8000/demo/\nLocal email inbox: http://localhost:8025"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
