"""Opt-in synthetic HTTP/PDF/worker/retrieval workload; no write retries."""

import argparse
import asyncio
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Lock
from uuid import UUID, uuid4

import asyncpg

from app.core.benchmark_metrics import Measurements
from scripts.benchmark_http import BenchmarkClient, BenchmarkFailure
from scripts.candidate_document_smoke import connection, sample_pdf
from scripts.docker_smoke import SMOKE_PASSWORD


@dataclass(frozen=True)
class WorkloadConfig:
    items: int = 4
    concurrency: int = 2
    deadline: int = 180
    polls: int = 240

    def __post_init__(self):
        for value, low, high in ((self.items, 1, 8), (self.concurrency, 1, 4),
                                 (self.deadline, 5, 180), (self.polls, 1, 360)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("Invalid workload bounds.")


def identifier(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise BenchmarkFailure("invalid_response")
    return value


class Workload:
    def __init__(self, client, measurements, config, *, run_id=None):
        self.run_id = uuid4().hex if run_id is None else run_id
        if not isinstance(self.run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", self.run_id):
            raise ValueError("Invalid workload run identity.")
        self.client, self.measurements, self.config = client, measurements, config
        self.slug, self.email = "workload-" + self.run_id, "workload-" + self.run_id + "@example.com"
        self.lock = Lock()
        self.items, self.user, self.organization, self.job = [], None, None, None
        self.cleaned = False

    def call(self, method, path, *, phase, expected=200, payload=None, binary=None, authenticated=True):
        return self.client.call(method, path, phase=phase, expected=expected, payload=payload,
                                binary=binary, token=self.token if authenticated else None)

    def prepare(self):
        credentials = {"email": self.email, "password": SMOKE_PASSWORD}
        user = self.call("POST", "/users/register", phase="register", expected=201,
                         payload=credentials, authenticated=False)
        self.user = identifier(user["id"])
        if user.get("email") != self.email:
            raise BenchmarkFailure("invalid_response")
        login = self.call("POST", "/auth/login", phase="login", payload=credentials, authenticated=False)
        self.token = login["access_token"]
        org = self.call("POST", "/organizations", phase="organization", expected=201,
                        payload={"name": "Synthetic workload", "slug": self.slug})
        self.organization = identifier(org["id"])
        if org.get("slug") != self.slug:
            raise BenchmarkFailure("invalid_response")
        self.root = "/organizations/" + self.organization
        job = self.call("POST", self.root + "/jobs", phase="job", expected=201,
                        payload={"title": "Synthetic reference role", "description": "Synthetic workload", "status": "open"})
        self.job = identifier(job["id"])
        if job.get("organization_id") != self.organization:
            raise BenchmarkFailure("invalid_response")
        self.call("PUT", self.root + "/jobs/" + self.job + "/search-profile", phase="profile",
                  payload={"q": "Candidate document smoke"})

    def one(self, position):
        started = time.monotonic()
        row = self.call("POST", self.root + "/candidates", phase="candidate", expected=201,
                        payload={"full_name": "Synthetic workload " + str(position)})
        candidate = identifier(row["id"])
        if row.get("organization_id") != self.organization:
            raise BenchmarkFailure("invalid_response")
        item = {"candidate": candidate, "application": None, "document": None, "states": set()}
        with self.lock:
            self.items.append(item)
        application = self.call("POST", self.root + "/applications", phase="application", expected=201,
                                payload={"job_id": self.job, "candidate_id": candidate})
        item["application"] = identifier(application["id"])
        if (application.get("candidate_id") != candidate or application.get("job_id") != self.job or
                application.get("organization_id") != self.organization or application.get("status") != "applied"):
            raise BenchmarkFailure("invalid_response")
        transitioned = self.call("POST", self.root + "/applications/" + item["application"] + "/transitions",
                                 phase="transition", payload={"status": "screening"})
        if transitioned.get("status") != "screening":
            raise BenchmarkFailure("invalid_response")
        documents = self.root + "/candidates/" + candidate + "/documents"
        uploaded = self.call("POST", documents + "?filename=synthetic.pdf", phase="upload",
                             expected=201, binary=sample_pdf())
        item["document"] = identifier(uploaded["id"])
        if uploaded.get("candidate_id") != candidate or uploaded.get("organization_id") != self.organization:
            raise BenchmarkFailure("invalid_response")
        item["path"] = documents + "/" + item["document"]
        queued_at = time.monotonic()
        queued = self.call("POST", item["path"] + "/extraction", phase="enqueue", expected=202, payload={})
        if queued.get("status") not in {"queued", "running"}:
            raise BenchmarkFailure("invalid_response")
        item["states"].add(queued.get("status"))
        for _ in range(self.config.polls):
            if time.monotonic() - queued_at >= self.config.deadline:
                raise BenchmarkFailure("extraction_deadline")
            result = self.call("GET", item["path"] + "/extraction", phase="poll")
            state = result.get("status")
            if state not in {"queued", "running", "succeeded", "failed"}:
                raise BenchmarkFailure("invalid_response")
            item["states"].add(state)
            if state == "failed":
                raise BenchmarkFailure("extraction_failed")
            if state == "succeeded":
                self.measurements.add("request_to_completion", (time.monotonic() - queued_at) * 1000)
                break
            time.sleep(.5)
        else:
            raise BenchmarkFailure("extraction_poll_limit")
        chunks = self.call("POST", item["path"] + "/chunks", phase="chunks", expected=201, payload={})
        if type(chunks.get("chunk_count")) is not int or chunks["chunk_count"] < 1:
            raise BenchmarkFailure("invalid_response")
        self.measurements.add("workflow", (time.monotonic() - started) * 1000)

    async def cleanup_metadata(self):
        database = await connection()
        try:
            async with database.transaction():
                await database.execute("SET LOCAL statement_timeout = '5s'")
                await database.execute("SET LOCAL lock_timeout = '1s'")
                org = UUID(self.organization)
                for table, values in (("applications", [item["application"] for item in self.items]),
                                      ("candidates", [item["candidate"] for item in self.items]),
                                      ("jobs", [self.job])):
                    result = await database.execute(f"DELETE FROM {table} WHERE organization_id=$1 AND id=ANY($2::uuid[])",
                                                    org, [UUID(value) for value in values])
                    if result != f"DELETE {len(values)}":
                        raise BenchmarkFailure("cleanup_incomplete")
                await database.execute("DELETE FROM organization_memberships WHERE organization_id=$1 AND user_id=$2", org, UUID(self.user))
                result = await database.execute("DELETE FROM organizations WHERE id=$1 AND slug=$2", org, self.slug)
                if result != "DELETE 1":
                    raise BenchmarkFailure("cleanup_incomplete")
                result = await database.execute("DELETE FROM users WHERE id=$1 AND email=$2", UUID(self.user), self.email)
                if result != "DELETE 1":
                    raise BenchmarkFailure("cleanup_incomplete")
        finally:
            await database.close()

    def run(self):
        self.prepare()
        executor = ThreadPoolExecutor(max_workers=min(self.config.items, self.config.concurrency))
        futures = []
        try:
            futures = [executor.submit(self.one, position) for position in range(self.config.items)]
            for future in as_completed(futures):
                future.result()
        finally:
            for future in futures:
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)
        page = self.call("GET", self.root + "/jobs/" + self.job + "/candidate-retrieval?limit=8", phase="retrieval")
        expected = {(item["candidate"], item["document"]) for item in self.items}
        observed = {(item["candidate_id"], item["document_id"]) for item in page["items"]}
        if page.get("total") != self.config.items or len(page["items"]) != self.config.items or observed != expected:
            raise BenchmarkFailure("retrieval_incomplete")
        for item in self.items:
            self.call("DELETE", item["path"], phase="delete_document", expected=204)
        asyncio.run(self.cleanup_metadata())
        self.cleaned = True

    def report(self, status, code=None):
        return {"version": "workload-benchmark-v1", "status": status, "run_id": self.run_id,
                "corpus_kind": "synthetic_pdf", "source_kind": "http_real_worker",
                "items": self.config.items, "concurrency": min(self.config.items, self.config.concurrency),
                "completed": sum("succeeded" in item["states"] for item in self.items),
                "queued_observed": sum("queued" in item["states"] for item in self.items),
                "running_observed": sum("running" in item["states"] for item in self.items),
                "cleanup": "completed" if self.cleaned else "manual_review_required",
                "diagnostic": code, "models_checked": False, "phases": self.measurements.report()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Create and remove this run's synthetic records only.")
    parser.add_argument("--base-url", default="http://api:8000")
    parser.add_argument("--items", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    measurements = Measurements()
    try:
        workload = Workload(BenchmarkClient(args.base_url, measurements), measurements,
                            WorkloadConfig(args.items, args.concurrency), run_id=args.run_id)
    except (ValueError, TypeError):
        print(json.dumps({"status": "failed", "diagnostic": "invalid_workload_arguments"}))
        return 2
    if not args.execute:
        print(json.dumps({"status": "plan", "items": args.items, "concurrency": min(args.items, args.concurrency),
                          "synthetic_writes_require": "--execute", "models_checked": False}))
        return 0
    try:
        workload.run()
        report, code = workload.report("passed"), 0
    except KeyboardInterrupt:
        report, code = workload.report("interrupted", "interrupted"), 130
    except BenchmarkFailure as error:
        report, code = workload.report("failed", error.code), 1
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, asyncpg.PostgresError, asyncpg.InterfaceError):
        report, code = workload.report("failed", "workload_unavailable"), 1
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
