import pytest

from app.core.resource_metrics import ResourceSummary, byte_count, resource_row


@pytest.mark.parametrize("text,expected", [("1MiB", 1048576), ("1.5GiB", 1610612736), ("10kB", 10000), ("0B", 0)])
def test_docker_memory_units(text, expected):
    assert byte_count(text) == expected


@pytest.mark.parametrize("row", [None, {}, {"CPUPerc": "NaN%", "MemUsage": "1MiB / 2MiB"},
                                 {"CPUPerc": "1%", "MemUsage": "3MiB / 2MiB"},
                                 {"CPUPerc": "1%", "MemUsage": None}],
                         ids=["not-object", "missing", "nonfinite", "over-limit", "wrong-type"])
def test_invalid_resource_rows_fail_closed(row):
    with pytest.raises((ValueError, TypeError)):
        resource_row(row)


def test_replicas_are_summed_per_snapshot_and_sampled_max_is_explicit():
    summary = ResourceSummary()
    summary.add({"extraction-worker": [{"CPUPerc": "80%", "MemUsage": "100MiB / 768MiB"},
                                        {"CPUPerc": "90%", "MemUsage": "200MiB / 768MiB"}]})
    result = summary.report()
    assert result["exact_peak"] is False and result["samples"] == 1
    row = result["services"]["extraction-worker"]
    assert row["sampled_cpu_max_percent"] == 170
    assert row["sampled_memory_max_bytes"] == 300 * 1048576
    with pytest.raises(ValueError):
        summary.add({"extraction-worker": [{"CPUPerc": "1%", "MemUsage": "1MiB / 768MiB"}]})
    assert summary.report() == result
