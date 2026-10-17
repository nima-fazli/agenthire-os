import pytest

from app.core.probe_metrics import ProbeSample, summarize


def test_nearest_rank_percentiles_include_failures_and_keep_tail_visible():
    samples = [ProbeSample(i, "ok", 200) for i in range(1, 20)]
    samples.append(ProbeSample(100, "timeout"))
    report = summarize(samples)
    assert report["latency_ms"] == {"p50": 10, "p95": 19, "max": 100}
    assert (report["passed"], report["failed"]) == (19, 1)
    assert report["outcomes"] == {"ok": 19, "timeout": 1}


def test_one_sample_and_unordered_samples_have_defined_percentiles():
    assert summarize([ProbeSample(4.12345, "ok")])["latency_ms"] == {"p50": 4.123, "p95": 4.123, "max": 4.123}
    assert summarize([ProbeSample(i, "ok") for i in (3, 1, 2)])["latency_ms"] == {"p50": 2, "p95": 3, "max": 3}


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "private"])
def test_nonfinite_or_invalid_durations_are_rejected(value):
    with pytest.raises(ValueError):
        ProbeSample(value, "ok")


@pytest.mark.parametrize("samples", [[], [ProbeSample(0, "ok")] * 65])
def test_sample_count_is_bounded(samples):
    with pytest.raises(ValueError):
        summarize(samples)


def test_arbitrary_error_text_cannot_enter_report():
    with pytest.raises(ValueError):
        ProbeSample(1, "private-server-error")
    with pytest.raises(ValueError):
        ProbeSample(1, "ok", True)
