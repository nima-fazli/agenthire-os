import math
from collections import Counter
from dataclasses import dataclass

OUTCOMES = frozenset({"ok", "http_error", "invalid_response", "timeout", "connection_error"})


@dataclass(frozen=True)
class ProbeSample:
    duration_ms: float
    outcome: str
    status_code: int = 0

    def __post_init__(self):
        if type(self.duration_ms) not in {int, float} or not math.isfinite(self.duration_ms) or self.duration_ms < 0:
            raise ValueError("Invalid probe duration.")
        if self.outcome not in OUTCOMES or type(self.status_code) is not int or not (
            self.status_code == 0 or 100 <= self.status_code <= 599
        ):
            raise ValueError("Invalid probe outcome.")


def summarize(samples: list[ProbeSample]) -> dict:
    if not 1 <= len(samples) <= 64:
        raise ValueError("A probe requires between 1 and 64 samples.")
    ordered = sorted(sample.duration_ms for sample in samples)
    counts = Counter(sample.outcome for sample in samples)
    return {
        "requests": len(samples), "passed": counts["ok"], "failed": len(samples) - counts["ok"],
        "outcomes": dict(sorted(counts.items())),
        "latency_ms": {"p50": round(ordered[math.ceil(len(ordered) * 0.50) - 1], 3),
                       "p95": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
                       "max": round(ordered[-1], 3)},
    }
