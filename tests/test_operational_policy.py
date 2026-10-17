import json

import pytest

from app.core.operational_policy import QueueLimits, assess_stack


def queues(age=10, expired=0):
    return {name: {"queued": 1, "running": 2, "expired_leases": expired,
                   "oldest_queued_seconds": age} for name in ("extraction", "embedding")}


def inventory():
    rows = [{"Service": name, "State": "running", "Health": "healthy"}
            for name in ("postgres", "api", "extraction-worker", "extraction-worker")]
    return [*rows, {"Service": "migrate", "State": "exited", "ExitCode": 0}]


def test_queue_limits_have_explicit_boundaries_and_do_not_mutate_snapshot():
    rows = queues()
    original = json.dumps(rows)
    assert QueueLimits(10, 0).assess(rows)["status"] == "within_limits"
    result = QueueLimits(9, 0).assess(rows)
    assert result["status"] == "attention"
    assert {alert["reason"] for alert in result["alerts"]} == {"queue_age"}
    assert json.dumps(rows) == original
    assert QueueLimits(100, 0).assess(queues(expired=1))["alerts"][0]["reason"] == "expired_leases"


@pytest.mark.parametrize("value", [-1, True, 1.5, 2_592_001])
def test_invalid_limits_are_rejected(value):
    with pytest.raises(ValueError):
        QueueLimits(value)


@pytest.mark.parametrize("value", [None, "private-error", {}, {"private": "secret"}])
def test_unavailable_or_foreign_queue_shape_never_echoes_content(value):
    assert QueueLimits(0, 0).assess(value) == {"status": "unavailable"}


def test_invalid_counters_fail_closed_and_empty_queue_does_not_raise_age_alert():
    rows = queues()
    rows["embedding"]["expired_leases"] = 3
    assert QueueLimits().assess(rows) == {"status": "unavailable"}
    rows = queues()
    rows["embedding"]["queued"] = True
    assert QueueLimits().assess(rows) == {"status": "unavailable"}
    rows = {name: {"queued": 0, "running": 0, "expired_leases": 0, "oldest_queued_seconds": 0}
            for name in ("extraction", "embedding")}
    assert QueueLimits(0, 0).assess(rows)["status"] == "within_limits"


def test_stack_requires_both_workers_and_completed_migration():
    rows = inventory()
    assert assess_stack(rows)["status"] == "ok"
    rows.pop(2)
    assert assess_stack(rows)["services"]["extraction-worker"]["status"] == "attention"
    assert assess_stack(rows, extraction_workers=1)["status"] == "ok"
    rows[-1]["ExitCode"] = 1
    assert assess_stack(rows, extraction_workers=1)["status"] == "attention"


def test_unhealthy_replica_is_not_hidden_by_healthy_replicas_or_extra_services():
    rows = inventory()
    rows.append({"Service": "extraction-worker", "State": "running", "Health": "unhealthy", "Name": "private-name"})
    report = assess_stack(rows)
    assert report["status"] == "attention"
    assert "private-name" not in json.dumps(report)


def test_semantic_inventory_is_explicit_and_never_proves_models_are_loaded():
    rows = inventory()
    assert assess_stack(rows, semantic=True)["status"] == "attention"
    rows.extend({"Service": name, "State": "running", "Health": "healthy"} for name in ("ollama", "embedding-worker"))
    assert assess_stack(rows, semantic=True)["status"] == "ok"
    assert assess_stack(rows, semantic=True)["models_checked"] is False
