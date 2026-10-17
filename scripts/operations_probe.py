"""Bounded local GET probes; no documents, writes, credentials or model calls."""

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core.probe_metrics import summarize
from app.core.probe_transport import local_target, probe


def measure(base_url, *, requests=20, concurrency=4, timeout=2.0, path="/ready"):
    local_target(base_url)
    if type(requests) is not int or not 1 <= requests <= 64 or type(concurrency) is not int or not 1 <= concurrency <= 8:
        raise ValueError("Requests must be 1..64 and concurrency 1..8.")
    if path not in {"/ready", "/health"} or type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0.05 <= timeout <= 5:
        raise ValueError("Invalid timeout or health route.")
    started = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=min(concurrency, requests))
    futures = []
    try:
        futures = [pool.submit(probe, base_url, path, timeout) for _ in range(requests)]
        report = summarize([future.result() for future in as_completed(futures)])
    finally:
        for future in futures:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
    return {"status": "passed" if not report["failed"] else "failed", "path": path,
            "concurrency": min(concurrency, requests), "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "models_checked": False, **report}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--path", choices=("/ready", "/health"), default="/ready")
    parser.add_argument("--max-p95-ms", type=float)
    args = parser.parse_args(argv)
    try:
        if args.max_p95_ms is not None and (not math.isfinite(args.max_p95_ms) or args.max_p95_ms <= 0):
            raise ValueError
        report = measure(args.base_url, requests=args.requests, concurrency=args.concurrency,
                         timeout=args.timeout, path=args.path)
        if args.max_p95_ms is not None:
            report["latency_limit_ms"] = args.max_p95_ms
            if report["latency_ms"]["p95"] > args.max_p95_ms:
                report["status"] = "failed"
                report["latency_limit_exceeded"] = True
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError):
        print(json.dumps({"status": "unavailable", "diagnostic": "invalid_or_unavailable_probe"}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
