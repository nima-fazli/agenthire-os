"""Private operator queue time series; no model calls or queue mutations."""

import argparse
import asyncio
import json
import math
import time

from app.core.operational_policy import QueueLimits
from scripts.runtime_diagnostics import queue_report


async def measure(*, samples=15, interval=1, reader=None, sleeper=asyncio.sleep):
    if type(samples) is not int or not 1 <= samples <= 60 or type(interval) not in {int, float} or not math.isfinite(interval) or not .25 <= interval <= 5:
        raise ValueError("Invalid queue sampling bounds.")
    engine = None
    if reader is None:
        from app.db.session import async_session_factory, engine

        async def reader():
            return await queue_report(async_session_factory)
    rows, started = [], time.monotonic()
    try:
        for index in range(samples):
            if index:
                await sleeper(interval)
            queues = await reader()
            if QueueLimits().assess(queues)["status"] == "unavailable":
                raise ValueError("Queue observations unavailable.")
            rows.append({"elapsed_seconds": round(time.monotonic() - started, 3), "queues": queues})
    finally:
        if engine is not None:
            await engine.dispose()
    return {"status": "captured", "models_checked": False, "source_kind": "global_queue_aggregates", "samples": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, choices=range(1, 61), default=15)
    parser.add_argument("--interval", type=float, default=1)
    args = parser.parse_args(argv)
    try:
        report, code = asyncio.run(measure(samples=args.samples, interval=args.interval)), 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError):
        report, code = {"status": "unavailable", "diagnostic": "queue_sampling_unavailable"}, 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
