import asyncio
import json

import pytest

from scripts import queue_watch as cli


def queues(count):
    return {name: {"queued": count, "running": 0, "expired_leases": 0, "oldest_queued_seconds": 2 if count else 0}
            for name in ("embedding", "extraction")}


def test_queue_time_series_observes_drain_without_inferring_worker_or_model_health():
    values = iter([queues(4), queues(0)])
    async def reader(): return next(values)
    async def sleep(seconds): assert seconds == .25
    report = asyncio.run(cli.measure(samples=2, interval=.25, reader=reader, sleeper=sleep))
    assert report["status"] == "captured" and not report["models_checked"]
    assert [row["queues"]["extraction"]["queued"] for row in report["samples"]] == [4, 0]
    assert "worker_healthy" not in json.dumps(report)


def test_unavailable_or_malformed_queues_fail_closed():
    async def reader(): return "unavailable"
    with pytest.raises(ValueError):
        asyncio.run(cli.measure(samples=1, reader=reader))


@pytest.mark.parametrize("options", [{"samples": True}, {"samples": 61}, {"interval": float("nan")}, {"interval": .01}],
                         ids=["boolean", "oversized", "nan", "too-fast"])
def test_invalid_sampling_bounds_do_not_query_database(options):
    async def reader(): pytest.fail("database used")
    with pytest.raises(ValueError):
        asyncio.run(cli.measure(reader=reader, **options))
