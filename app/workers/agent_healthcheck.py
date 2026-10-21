"""Check the worker heartbeat with the Python standard library only.

Docker runs this file directly so application imports cannot consume the
healthcheck deadline or initialize another worker/model client.
"""

import argparse
import stat
import sys
import time
from pathlib import Path

HEARTBEAT = Path("/tmp/agenthire-agents.heartbeat")
MAX_AGE_SECONDS = 300


def healthcheck(path=HEARTBEAT):
    try:
        info = path.stat()
    except OSError:
        return False, "Agent worker heartbeat is unavailable."
    if not stat.S_ISREG(info.st_mode):
        return False, "Agent worker heartbeat is not a regular file."
    age = time.time() - info.st_mtime
    if not 0 <= age < MAX_AGE_SECONDS:
        return False, "Agent worker heartbeat is stale or has an invalid timestamp."
    return True, ""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heartbeat", type=Path, default=HEARTBEAT)
    args = parser.parse_args(argv)
    healthy, reason = healthcheck(args.heartbeat)
    if not healthy:
        print(reason, file=sys.stderr)
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
