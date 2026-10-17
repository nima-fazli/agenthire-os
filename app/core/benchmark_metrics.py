"""Bounded operator measurements; no source content or resource identifiers."""

import math
from collections import defaultdict
from threading import Lock

PHASES = frozenset({
    "register", "login", "organization", "job", "profile", "candidate",
    "application", "transition", "upload", "enqueue", "poll", "chunks",
    "workflow", "request_to_completion", "retrieval", "delete_document",
    "embedding", "chat",
})


def distribution(values):
    if not 1 <= len(values) <= 4096 or any(
        type(value) not in {int, float} or not math.isfinite(value) or value < 0
        for value in values
    ):
        raise ValueError("Invalid measurement samples.")
    ordered = sorted(values)
    return {"samples": len(ordered), "p50_ms": round(ordered[math.ceil(len(ordered) * .5) - 1], 3),
            "p95_ms": round(ordered[math.ceil(len(ordered) * .95) - 1], 3),
            "max_ms": round(ordered[-1], 3)}


class Measurements:
    def __init__(self):
        self._lock = Lock()
        self._values = defaultdict(list)
        self._failures = defaultdict(int)

    def add(self, phase, elapsed_ms, *, failed=False):
        if phase not in PHASES or type(failed) is not bool:
            raise ValueError("Invalid measurement phase.")
        distribution([elapsed_ms])
        with self._lock:
            if len(self._values[phase]) >= 4096:
                raise ValueError("Measurement limit exceeded.")
            self._values[phase].append(elapsed_ms)
            self._failures[phase] += failed

    def report(self):
        with self._lock:
            return {phase: distribution(values) | {"failed": self._failures[phase]}
                    for phase, values in sorted(self._values.items())}
