import asyncio
from urllib.request import Request, urlopen
from uuid import uuid4

from app.web.router import ASSETS, UI_HEADERS
from scripts.candidate_smoke import cleanup_candidate_rows
from scripts.docker_smoke import (
    API_BASE_URL,
    SMOKE_PASSWORD,
    SmokeFailure,
    expect_status,
    log_ok,
    request_json,
)
from scripts.smoke_cleanup import cleanup_smoke_data


def verify_shell():
    for name, content_type in ASSETS.items():
        path = "/workspace/" if name == "index.html" else f"/workspace/assets/{name}"
        with urlopen(Request(f"{API_BASE_URL}{path}"), timeout=10) as response:
            if response.status != 200 or not response.headers.get("Content-Type", "").startswith(content_type):
                raise SmokeFailure("Recruiter UI asset transport failed.")
            if any(response.headers.get(key) != value for key, value in UI_HEADERS.items()):
                raise SmokeFailure("Recruiter UI security/cache headers changed.")
            if not response.read():
                raise SmokeFailure("Recruiter UI asset was empty.")
    unknown = request_json("GET", "/workspace/assets/router.py")
    expect_status(unknown, 404, step="private UI source denial")
    log_ok("Public recruiter shell and all local assets with security/no-store headers")


def verify_workflow(owner, outsider, slug):
    def call(method, path, token=None, payload=None, status=200):
        response = request_json(method, path, token=token, payload=payload)
        expect_status(response, status, step="recruiter UI real HTTP contract")
        return response.body

    tokens = []
    for email in (owner, outsider):
        call("POST", "/users/register", payload={"email": email, "password": SMOKE_PASSWORD}, status=201)
        tokens.append(call("POST", "/auth/login", payload={"email": email, "password": SMOKE_PASSWORD})["access_token"])
    token, foreign_token = tokens
    if call("GET", "/users/me", token)["email"] != owner:
        raise SmokeFailure("Recruiter identity contract changed.")
    org = call("POST", "/organizations", token, {"name": "Recruiter UI fixture", "slug": slug}, 201)
    root = f"/organizations/{org['id']}"
    job = call("POST", f"{root}/jobs", token, {"title": "Backend Engineer", "description": "Synthetic UI acceptance", "status": "draft"}, 201)
    candidate = call("POST", f"{root}/candidates", token, {"full_name": "داوطلب مصنوعی", "headline": "Python Engineer"}, 201)
    job_path = f"{root}/jobs/{job['id']}"
    candidate_path = f"{root}/candidates/{candidate['id']}"
    if not any(item["id"] == candidate["id"] for item in call("GET", f"{root}/candidates", token)):
        raise SmokeFailure("Recruiter candidate listing changed.")
    call("PUT", f"{job_path}/search-profile", token, {"q": "Python"})
    criteria = {"criteria": [{"key": "python", "label": "Python", "q": "Python", "importance": "required"}]}
    call("PUT", f"{job_path}/match-profile", token, criteria)
    if call("GET", f"{job_path}/search-profile", token)["q"] != "Python":
        raise SmokeFailure("Recruiter search profile persistence changed.")
    if call("GET", f"{job_path}/match-profile", token)["criteria"][0]["key"] != "python":
        raise SmokeFailure("Recruiter profile persistence changed.")
    evidence = call("GET", f"{job_path}/candidates/{candidate['id']}/match-evidence", token)
    if evidence["summary"]["source_status"] != "no_documents" or evidence["criteria"][0]["evidence"] is not None:
        raise SmokeFailure("Recruiter empty-source meaning changed.")
    if call("GET", f"{candidate_path}/documents?limit=10&offset=0", token) != []:
        raise SmokeFailure("Recruiter private document listing changed.")
    if call("GET", f"{job_path}/candidate-retrieval?limit=20&offset=0", token)["total"] != 0:
        raise SmokeFailure("Recruiter empty retrieval contract changed.")
    for path in (f"{root}/jobs", candidate_path, f"{job_path}/match-profile", f"{job_path}/candidates/{candidate['id']}/match-evidence"):
        call("GET", path, foreign_token, status=404)
    log_ok("Real authenticated organization/job/candidate/profile/evidence APIs and foreign-member denial")


async def main():
    run_id = uuid4().hex
    owner, outsider = f"ui-owner-{run_id}@example.com", f"ui-outsider-{run_id}@example.com"
    slug = f"ui-smoke-{run_id}"
    try:
        verify_shell()
        verify_workflow(owner, outsider, slug)
    finally:
        try:
            await cleanup_candidate_rows(slug)
        finally:
            await cleanup_smoke_data(organization_slug=slug, user_emails=(owner, outsider))
    log_ok("Only this smoke's random-ID fixture rows cleaned")
    print("[success] Recruiter UI real-stack HTTP contracts passed; this is not browser automation.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
