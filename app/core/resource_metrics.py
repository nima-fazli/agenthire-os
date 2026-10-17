"""Docker CLI usage samples are working-set observations, not process RSS peaks."""

import math
import re

SERVICES = frozenset({"api", "postgres", "extraction-worker", "embedding-worker", "ollama"})
UNITS = {"B": 1, **{prefix + "B": 1000 ** n for n, prefix in enumerate("kMGTPE", 1)},
         **{prefix + "iB": 1024 ** n for n, prefix in enumerate("KMGTPE", 1)}}


def byte_count(value):
    if not isinstance(value, str):
        raise TypeError("Invalid memory sample.")
    match = re.fullmatch(r"([0-9]{1,12}(?:\.[0-9]{1,6})?)\s*([A-Za-z]+)", value.strip())
    if match is None or match[2] not in UNITS:
        raise ValueError("Invalid memory sample.")
    result = float(match[1]) * UNITS[match[2]]
    if not math.isfinite(result) or result > 2 ** 64:
        raise ValueError("Invalid memory sample.")
    return int(result)


def resource_row(row):
    if not isinstance(row, dict):
        raise TypeError("Invalid resource sample.")
    cpu = row.get("CPUPerc")
    if not isinstance(cpu, str) or not re.fullmatch(r"[0-9]{1,7}(?:\.[0-9]{1,6})?%", cpu):
        raise ValueError("Invalid CPU sample.")
    if not isinstance(row.get("MemUsage"), str):
        raise TypeError("Invalid memory sample.")
    memory = row["MemUsage"].split("/")
    if len(memory) != 2:
        raise ValueError("Invalid memory sample.")
    used, limit = map(byte_count, memory)
    if not limit or used > limit:
        raise ValueError("Invalid memory sample.")
    return {"cpu_percent": float(cpu[:-1]), "memory_bytes": used, "limit_bytes": limit}


class ResourceSummary:
    def __init__(self):
        self.samples = 0
        self.services = {}

    def add(self, snapshot):
        if self.samples >= 600 or not snapshot or set(snapshot) - SERVICES:
            raise ValueError("Invalid resource snapshot.")
        if self.samples and set(snapshot) != set(self.services):
            raise ValueError("Resource topology changed.")
        parsed = {}
        for name, rows in snapshot.items():
            if not 1 <= len(rows) <= 8:
                raise ValueError("Invalid replica count.")
            values = [resource_row(row) for row in rows]
            parsed[name] = {"replicas": len(values),
                "cpu_percent": sum(v["cpu_percent"] for v in values),
                "memory_bytes": sum(v["memory_bytes"] for v in values),
                "limit_bytes": sum(v["limit_bytes"] for v in values)}
            previous = self.services.get(name)
            if previous and (previous["replicas"] != len(rows) or previous["limit_bytes"] != parsed[name]["limit_bytes"]):
                raise ValueError("Resource topology changed.")
        for name, value in parsed.items():
            previous = self.services.get(name, {})
            self.services[name] = {"replicas": value["replicas"], "limit_bytes": value["limit_bytes"],
                "sampled_memory_max_bytes": max(previous.get("sampled_memory_max_bytes", 0), value["memory_bytes"]),
                "sampled_cpu_max_percent": round(max(previous.get("sampled_cpu_max_percent", 0), value["cpu_percent"]), 3)}
        self.samples += 1

    def report(self):
        return {"samples": self.samples, "metric": "docker_stats_memory_usage",
                "exact_peak": False, "services": dict(sorted(self.services.items()))}
