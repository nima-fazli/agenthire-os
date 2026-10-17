from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.benchmark_metrics import Measurements, distribution


def test_nearest_rank_includes_slow_attempt_and_failures():
    metrics = Measurements()
    for number in range(1, 21):
        metrics.add("poll", number, failed=number == 20)
    assert metrics.report()["poll"] == {"samples": 20, "p50_ms": 10, "p95_ms": 19, "max_ms": 20, "failed": 1}


@pytest.mark.parametrize("values", [[], [True], [float("nan")], [float("inf")], [-1], [0] * 4097],
                         ids=["empty", "boolean", "nan", "infinity", "negative", "oversized"])
def test_invalid_durations_are_rejected(values):
    with pytest.raises(ValueError):
        distribution(values)


def test_threaded_measurements_keep_all_samples_and_hide_arbitrary_phase_labels():
    metrics = Measurements()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: metrics.add("candidate", 1), range(80)))
    assert metrics.report()["candidate"]["samples"] == 80
    with pytest.raises(ValueError):
        metrics.add("private-token", 1)
    assert "private" not in str(metrics.report())
