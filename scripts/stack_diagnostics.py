"""Read-only host Compose inventory; reports aggregate health, never raw output."""

import argparse
import json
import re
import subprocess
from pathlib import Path

from app.core.operational_policy import assess_stack
from scripts.ci_plan import repository_root


def parse_inventory(value: str) -> list[dict]:
    if len(value) > 1_048_576:
        raise ValueError("Inventory exceeds the diagnostic limit.")
    value = value.strip()
    if not value:
        return []
    rows = json.loads(value) if value.startswith("[") else [json.loads(line) for line in value.splitlines() if line.strip()]
    if not isinstance(rows, list) or len(rows) > 64:
        raise ValueError("Invalid inventory.")
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("Service"), str):
            raise TypeError("Invalid inventory.")
        identity = row.get("ID")
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{12,64}", identity) or identity in ids:
            raise ValueError("Invalid inventory.")
        ids.add(identity)
    return rows


def collect(root: Path, *, workers=2, semantic=False, runner=subprocess.run):
    root = repository_root(root)
    command = ("docker", "compose", "--file", str(root / "compose.yaml"), "ps", "--all", "--format", "json")
    result = runner(command, cwd=root, capture_output=True, text=True, timeout=15,
                    check=False, stdin=subprocess.DEVNULL)
    if result.returncode:
        raise ValueError("Compose inventory unavailable.")
    return assess_stack(parse_inventory(result.stdout), extraction_workers=workers, semantic=semantic)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extraction-workers", type=int, choices=range(1, 9), default=2)
    parser.add_argument("--semantic", action="store_true", help="Also require existing embedding/Ollama containers.")
    args = parser.parse_args(argv)
    try:
        report = collect(Path.cwd(), workers=args.extraction_workers, semantic=args.semantic)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"status": "unavailable", "diagnostic": "compose_unavailable"}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
