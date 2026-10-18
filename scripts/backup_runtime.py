"""Owned Docker operations; credentials and raw subprocess output stay private."""

import json
import os
import re
import subprocess
import time

from app.core.backup_store import read_json, write_json
from scripts.ci_plan import validate_project_name

SERVICES = ("api", "extraction-worker", "embedding-worker")
IDENTITY_CODE = """import hashlib,json
from app.core.config import get_settings
s=get_settings()
print(hashlib.sha256(json.dumps([s.postgres_host,s.postgres_port,s.postgres_db,s.postgres_user,s.postgres_password.get_secret_value(),s.jwt_secret.get_secret_value()]).encode()).hexdigest())
"""
INSPECT = ('{"id":{{json .Id}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
           '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
           '"image":{{json .Image}},"running":{{json .State.Running}},'
           '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}}')


class BackupFailure(Exception):
    pass


class Runtime:
    def __init__(self, root, project, prefix, environment, *, runner=subprocess.run):
        if project != "agenthire-os":
            validate_project_name(project)
        self.root, self.project, self.prefix = root, project, tuple(prefix)
        self.environment, self.runner = environment, runner

    def raw(self, command, *, timeout=180, output=None, input_file=None):
        result = self.runner(tuple(command), cwd=self.root, env=self.environment, check=False,
                             stdin=input_file if input_file is not None else subprocess.DEVNULL,
                             stdout=output if output is not None else subprocess.PIPE,
                             stderr=subprocess.PIPE, timeout=timeout)
        if result.returncode:
            raise BackupFailure("backup_command_failed")
        if output is not None:
            output.flush()
            os.fsync(output.fileno())
            if output.tell() > 256 * 1024 * 1024:
                raise BackupFailure("backup_output_limit")
            return ""
        return result.stdout.decode("utf-8") if isinstance(result.stdout, bytes) else result.stdout

    def call(self, arguments, **options):
        return self.raw((*self.prefix, *arguments), **options)

    def helper(self, action, *, output=None, input_file=None):
        arguments = ("--profile", "smoke", "run", "--rm", "--no-deps", "-T",
                     "--env", "AGENTHIRE_BACKUP_PROJECT=" + self.project,
                     "--env", "AGENTHIRE_RECOVERY_PROJECT=" + self.project,
                     "smoke", "python", "-m", "scripts.backup_objects", action, "--project", self.project)
        text = self.call(arguments, output=output, input_file=input_file)
        if output is not None:
            return None
        value = json.loads(text.splitlines()[-1])
        if value.get("status") != "passed":
            raise BackupFailure("backup_object_gate_failed")
        return value

    def running(self, service):
        values = self.call(("--profile", "semantic", "ps", "--status", "running", "--quiet", service)).splitlines()
        if any(not re.fullmatch(r"[0-9a-f]{12,64}", value) for value in values) or len(values) > 2:
            raise ValueError("Invalid writer inventory.")
        return values

    def inspect(self, identity):
        if not re.fullmatch(r"[0-9a-f]{12,64}", identity):
            raise ValueError("Invalid recorded container.")
        value = json.loads(self.raw(("docker", "inspect", "--format", INSPECT, identity)))
        if (set(value) != {"id", "project", "service", "image", "running", "health"}
                or not re.fullmatch(r"[0-9a-f]{64}", value["id"]) or not value["id"].startswith(identity)
                or value["project"] != self.project or value["service"] not in SERVICES
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["image"])):
            raise ValueError("Container ownership mismatch.")
        return value

    def writers(self):
        records = []
        for service in SERVICES:
            identities = self.running(service)
            minimum, maximum = (1, 1) if service == "api" else ((2, 2) if service == "extraction-worker" else (0, 1))
            if not minimum <= len(identities) <= maximum:
                raise ValueError("Expected writer replicas unavailable.")
            for identity in identities:
                value = self.inspect(identity)
                if value["service"] != service or not value["running"] or value["health"] != "healthy":
                    raise ValueError("Healthy owned writers required.")
                records.append({key: value[key] for key in ("id", "project", "service", "image")})
        return records

    def stopped(self, records):
        if any(self.running(service) for service in SERVICES):
            raise BackupFailure("source_writers_not_stopped")

    def resume(self, records):
        validate_records(records, self.project)
        failed = False
        for record in sorted(records, key=lambda row: row["service"] == "api"):
            try:
                actual = self.inspect(record["id"])
                if any(actual[key] != value for key, value in record.items()):
                    raise ValueError("Recorded source changed.")
                self.raw(("docker", "start", record["id"]), timeout=60)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, BackupFailure):
                failed = True
        if failed:
            raise BackupFailure("source_resume_attention")
        deadline = time.monotonic() + 90
        while True:
            actual = [self.inspect(record["id"]) for record in records]
            if all(row["running"] and row["health"] == "healthy" for row in actual):
                return
            if time.monotonic() >= deadline:
                raise BackupFailure("source_resume_attention")
            time.sleep(1)


def validate_records(records, project):
    if not isinstance(records, list) or not 3 <= len(records) <= 4:
        raise ValueError("Invalid resume inventory.")
    counts, identities = {}, set()
    for row in records:
        if (not isinstance(row, dict) or set(row) != {"id", "project", "service", "image"}
                or row["project"] != project or row["service"] not in SERVICES
                or not re.fullmatch(r"[0-9a-f]{64}", row["id"]) or row["id"] in identities
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", row["image"])):
            raise ValueError("Invalid resume ownership.")
        identities.add(row["id"])
        counts[row["service"]] = counts.get(row["service"], 0) + 1
    if counts.get("api") != 1 or counts.get("extraction-worker") != 2 or counts.get("embedding-worker", 0) > 1:
        raise ValueError("Invalid recorded replica counts.")


def record_pause(store, runtime, records):
    validate_records(records, runtime.project)
    journal = {"store_id": store.check(), "project": runtime.project, "writers": records}
    write_json(store.root / "journal.json", journal)
    return journal


def resume_recorded(store, runtime):
    journal = read_json(store.root / "journal.json", 8192)
    if (set(journal) != {"store_id", "project", "writers"}
            or journal["store_id"] != store.check() or journal["project"] != runtime.project):
        raise ValueError("Resume journal ownership mismatch.")
    runtime.resume(journal["writers"])
    (store.root / "journal.json").unlink()
