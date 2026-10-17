"""Decisions over private aggregates; never infer model quality or throughput."""

from dataclasses import dataclass


@dataclass(frozen=True)
class QueueLimits:
    max_age_seconds: int | None = None
    max_expired_leases: int | None = None

    def __post_init__(self):
        for value in (self.max_age_seconds, self.max_expired_leases):
            if value is not None and (type(value) is not int or not 0 <= value <= 2_592_000):
                raise ValueError("Queue limits must be integers from 0 to 2592000.")

    def assess(self, queues) -> dict:
        fields = {"queued", "running", "expired_leases", "oldest_queued_seconds"}
        if not isinstance(queues, dict) or set(queues) != {"extraction", "embedding"}:
            return {"status": "unavailable"}
        alerts = []
        for name, row in queues.items():
            if not isinstance(row, dict) or set(row) != fields or any(
                type(value) is not int or value < 0 for value in row.values()
            ) or row["expired_leases"] > row["running"]:
                return {"status": "unavailable"}
            if self.max_age_seconds is not None and row["queued"] and row["oldest_queued_seconds"] > self.max_age_seconds:
                alerts.append({"queue": name, "reason": "queue_age"})
            if self.max_expired_leases is not None and row["expired_leases"] > self.max_expired_leases:
                alerts.append({"queue": name, "reason": "expired_leases"})
        return {"status": "attention" if alerts else "within_limits", "alerts": alerts}


def assess_stack(rows: list[dict], *, extraction_workers: int = 2, semantic: bool = False) -> dict:
    if type(extraction_workers) is not int or not 1 <= extraction_workers <= 8:
        raise ValueError("Expected extraction workers must be between 1 and 8.")
    required = {"postgres": 1, "api": 1, "extraction-worker": extraction_workers}
    if semantic:
        required.update({"embedding-worker": 1, "ollama": 1})
    services = {}
    for name, minimum in required.items():
        members = [row for row in rows if row.get("Service") == name]
        healthy = sum(row.get("State") == "running" and row.get("Health") == "healthy" for row in members)
        services[name] = {"observed": len(members), "healthy": healthy, "minimum": minimum,
                          "status": "ok" if healthy >= minimum and healthy == len(members) else "attention"}
    migrations = [row for row in rows if row.get("Service") == "migrate"]
    completed = sum(row.get("State") == "exited" and type(row.get("ExitCode")) is int
                    and row["ExitCode"] == 0 for row in migrations)
    services["migrate"] = {"observed": len(migrations), "completed": completed,
                           "status": "ok" if completed and completed == len(migrations) else "attention"}
    return {"status": "ok" if all(row["status"] == "ok" for row in services.values()) else "attention",
            "models_checked": False, "services": services}
