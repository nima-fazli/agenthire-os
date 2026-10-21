"""Exercise the actual seeded local API, worker, verification SMTP and approval flow."""

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

from app.tools.demo_seed import PASSWORD, stable


def request(base, path, *, token=None, method="GET", data=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        base + path,
        method=method,
        headers=headers,
        data=json.dumps(data).encode() if data is not None else None,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=15) as response:
            raw = response.read(2 * 1024 * 1024)
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        try:
            code = (
                json.loads(error.read(16384)).get("error", {}).get("code", "HTTP_ERROR")
            )
        except ValueError:
            code = "HTTP_ERROR"
        finally:
            error.close()
        raise RuntimeError(f"HTTP {error.code}: {code}") from None


def wait_for(read, predicate, seconds=60):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = read()
        if predicate(value):
            return value
        time.sleep(0.5)
    raise RuntimeError("Timed out waiting for local worker or email delivery.")


def verification_code(inbox, email):
    listing = request(inbox, "/api/v1/messages")
    for item in listing.get("messages", []):
        if any(x.get("Address", "").lower() == email for x in item.get("To", [])):
            detail = request(
                inbox, "/api/v1/message/" + urllib.parse.quote(item["ID"], safe="")
            )
            match = re.search(r"code is ([0-9]{6})", detail.get("Text", ""))
            if match:
                return match.group(1)
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--mailpit-url", default="http://127.0.0.1:8025")
    args = parser.parse_args(argv)
    for url in [args.base_url, args.mailpit_url]:
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            parser.error(
                "This synthetic smoke test targets direct local HTTP services only."
            )
    base, inbox = args.base_url.rstrip("/"), args.mailpit_url.rstrip("/")
    oid, jid = str(stable("organization")), str(stable("job"))
    owner = request(
        base,
        "/auth/login",
        method="POST",
        data={"email": "owner@agenthire.example.com", "password": PASSWORD},
    )["access_token"]
    email = f"smoke-{uuid4().hex[:12]}@agenthire.example.com"
    request(
        base,
        "/users/register",
        method="POST",
        data={"email": email, "password": PASSWORD},
    )
    token = request(
        base, "/auth/login", method="POST", data={"email": email, "password": PASSWORD}
    )["access_token"]
    request(base, "/portal/api/verification/request", method="POST", token=token)
    code = wait_for(lambda: verification_code(inbox, email), bool)
    request(
        base,
        "/portal/api/verification/confirm",
        method="POST",
        token=token,
        data={"code": code},
    )
    assert any(j["id"] == jid for j in request(base, "/public/jobs")["items"])
    draft = request(
        base,
        "/portal/api/drafts",
        token=token,
        method="POST",
        data={
            "job_id": jid,
            "full_name": "Synthetic Smoke Applicant",
            "resume_text": "Built Python backend APIs.\nMaintained PostgreSQL migrations and indexes.\nWrote integration tests.",
        },
    )
    submitted = request(
        base,
        f"/portal/api/applications/{draft['id']}/submit",
        token=token,
        method="POST",
        data={"mode": "replay"},
    )
    rid = submitted["run_id"]
    run = wait_for(
        lambda: request(base, f"/organizations/{oid}/agent-runs/{rid}", token=owner),
        lambda r: r["status"] in {"waiting_approval", "failed"},
    )
    assert run["status"] == "waiting_approval", str(run["failure_code"])
    assert run["report"]["question_keys"] == ["docker"]
    request(
        base,
        f"/organizations/{oid}/agent-runs/{rid}/approval",
        token=owner,
        method="POST",
        data={"decision": "approve", "source_fingerprint": run["source_fingerprint"]},
    )
    application = next(
        a
        for a in request(base, "/portal/api/applications", token=token)
        if a["id"] == draft["id"]
    )
    assert application["status"] == "Additional information requested"
    request(
        base,
        f"/portal/api/applications/{draft['id']}/answer",
        token=token,
        method="POST",
        data={
            "question_revision": application["question_revision"],
            "text": "Built Docker images for Python services and deployed containers.",
            "mode": "replay",
        },
    )
    asked = request(
        base,
        f"/portal/api/applications/{draft['id']}/ask",
        token=token,
        method="POST",
        data={"goal": "What is my application status?", "mode": "replay"},
    )
    answer = wait_for(
        lambda: request(base, f"/portal/api/agent-runs/{asked['id']}", token=token),
        lambda r: r["status"] in {"completed", "failed"},
    )
    assert answer["status"] == "completed" and answer["answer"]
    try:
        request(base, f"/organizations/{oid}/agent-runs/{rid}", token=token)
    except RuntimeError as error:
        assert "404" in str(error) or "403" in str(error)
    else:
        raise AssertionError("Applicant could read a private company review")
    print(
        json.dumps(
            {
                "status": "passed",
                "mode": "replay",
                "live_quality_claim": False,
                "checks": [
                    "verification_via_smtp",
                    "public_job",
                    "apply",
                    "worker_review",
                    "human_approval",
                    "clarification_reply",
                    "applicant_agent",
                    "private_company_scope_denied",
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
