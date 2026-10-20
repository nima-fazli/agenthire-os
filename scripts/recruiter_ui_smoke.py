import asyncio
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from app.web.router import ASSETS, UI_HEADERS
from scripts.application_smoke import cleanup_application_rows
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
            body = response.read()
            if not body:
                raise SmokeFailure("Recruiter UI asset was empty.")
            if name == "index.html" and b'<html lang="en" dir="ltr">' not in body:
                raise SmokeFailure("Recruiter workspace must use English and left-to-right layout.")
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
    candidate = call("POST", f"{root}/candidates", token, {
        "full_name": "Synthetic Candidate", "headline": "Python Engineer", "email": f"ui-{slug}@example.com",
    }, 201)
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
    for name in ("Literal_100%", "LiteralX100Z"):
        call("POST", f"{root}/candidates", token, {"full_name": name}, 201)
    first = call("GET", f"{root}/recruiting/candidates?limit=2&offset=0", token)
    second = call("GET", f"{root}/recruiting/candidates?limit=2&offset=2", token)
    identifiers = [row["id"] for row in first["items"] + second["items"]]
    if first["total"] != 3 or second["total"] != 3 or len(set(identifiers)) != 3:
        raise SmokeFailure("Recruiter database pagination failed.")
    literal = call("GET", f"{root}/recruiting/candidates?{urlencode({'q': '_100%'})}", token)
    if literal["total"] != 1 or literal["items"][0]["full_name"] != "Literal_100%":
        raise SmokeFailure("Recruiter literal search escaped incorrectly.")
    if call("GET", f"/organizations/page?{urlencode({'q': slug})}", token)["total"] != 1:
        raise SmokeFailure("Recruiter organization page scope changed.")
    empty_page = call("GET", f"{root}/recruiting/candidates?offset=100", token)
    if empty_page["items"] or empty_page["total"] != 3:
        raise SmokeFailure("Recruiter empty page lost its total.")
    job_edit = {"title": "Updated Backend", "description": "Synthetic UI acceptance",
                "status": "open", "expected_updated_at": job["updated_at"]}
    changed = call("PUT", f"{root}/recruiting/jobs/{job['id']}", token, job_edit)
    if changed["title"] != "Updated Backend" or changed["status"] != "open":
        raise SmokeFailure("Recruiter job editing failed.")
    stale = call("PUT", f"{root}/recruiting/jobs/{job['id']}", token, job_edit, 409)
    if stale["error"]["code"] != "RECORD_CHANGED":
        raise SmokeFailure("Recruiter edit version protection failed.")
    candidate_edit = {"full_name": "Updated Candidate", "email": None, "headline": "Python Engineer",
                      "expected_updated_at": candidate["updated_at"]}
    changed = call("PUT", f"{root}/recruiting/candidates/{candidate['id']}", token, candidate_edit)
    if changed["full_name"] != "Updated Candidate" or changed["email"] is not None:
        raise SmokeFailure("Recruiter candidate replacement failed.")
    application = call("POST", f"{root}/applications", token,
                       {"job_id": job["id"], "candidate_id": candidate["id"]}, 201)
    applications = f"{root}/recruiting/applications?job_id={job['id']}"
    page = call("GET", applications, token)
    if page["total"] != 1 or page["items"][0]["allowed_statuses"] != ["rejected", "screening"]:
        raise SmokeFailure("Recruiter application choices changed.")
    for target in ("screening", "interview", "offer", "hired"):
        result = call("POST", f"{root}/applications/{application['id']}/transitions", token, {"status": target})
        if result["status"] != target:
            raise SmokeFailure("Recruiter application transition failed.")
    if call("GET", applications, token)["items"][0]["allowed_statuses"]:
        raise SmokeFailure("A final application still offers a transition.")
    for path in (f"{root}/jobs", candidate_path, f"{job_path}/match-profile", f"{job_path}/candidates/{candidate['id']}/match-evidence",
                 f"{root}/recruiting/jobs", f"{root}/recruiting/candidates", applications):
        call("GET", path, foreign_token, status=404)
    call("PUT", f"{root}/recruiting/jobs/{job['id']}", foreign_token, job_edit, 404)
    log_ok("Recruiting pages, literal search, versioned edits, transitions and tenant denial")
    verify_access(call, root, owner, outsider, token, foreign_token)

def verify_access(call, root, owner, outsider, token, foreign_token):
    password = {"current_password": SMOKE_PASSWORD}
    info = call("GET", root + "/access", token)
    if info["role"] != "owner" or not info["can_manage"] or len(info["members"]) != 1:
        raise SmokeFailure("Creator ownership or member visibility failed.")
    call("POST", root + "/access/invitations", token,
         {"email": outsider, "role": "owner", **password}, 422)
    created = call("POST", root + "/access/invitations", token,
                   {"email": outsider, "role": "viewer", **password}, 201)
    if "token" in str(call("GET", root + "/access", token)):
        raise SmokeFailure("Invitation secret leaked into access reads.")
    call("POST", "/access/invitations/accept", token, {"token": created["token"]}, 404)
    accepted = call("POST", "/access/invitations/accept", foreign_token, {"token": created["token"]})
    if accepted["role"] != "viewer":
        raise SmokeFailure("Invitation role changed.")
    call("POST", "/access/invitations/accept", foreign_token, {"token": created["token"]}, 404)
    view = call("GET", root + "/access", foreign_token)
    if view["members"] or view["events"] or view["can_write"]:
        raise SmokeFailure("Viewer received owner metadata or mutation capability.")
    call("POST", root + "/jobs", foreign_token, {"title": "Denied", "description": "Synthetic"}, 403)
    call("POST", root + "/access/invitations", foreign_token,
         {"email": owner, "role": "recruiter", **password}, 403)
    members = call("GET", root + "/access", token)["members"]
    own = next(item for item in members if item["email"] == owner)
    member = next(item for item in members if item["email"] == outsider)
    own_path, member_path = root + "/access/members/" + own["id"], root + "/access/members/" + member["id"]
    call("DELETE", own_path, token, {"expected_role": "owner", **password}, 409)
    call("PUT", member_path, token, {"role": "recruiter", "expected_role": "viewer", **password})
    call("PUT", member_path, token, {"role": "owner", "expected_role": "viewer", **password}, 409)
    call("POST", root + "/jobs", foreign_token, {"title": "Recruiter write", "description": "Synthetic"}, 201)
    call("POST", root + "/access/invitations", foreign_token,
         {"email": owner, "role": "viewer", **password}, 403)
    call("DELETE", member_path, token, {"expected_role": "recruiter", **password})
    call("GET", root + "/jobs", foreign_token, status=404)
    revoked = call("POST", root + "/access/invitations", token,
                   {"email": outsider, "role": "recruiter", **password}, 201)
    call("DELETE", root + "/access/invitations/" + revoked["id"], token, password, 204)
    call("POST", "/access/invitations/accept", foreign_token, {"token": revoked["token"]}, 404)
    events = call("GET", root + "/access", token)["events"]
    if not {"role_changed", "member_removed", "invitation_accepted", "invitation_revoked"} <= {e["action"] for e in events}:
        raise SmokeFailure("Access audit trail is incomplete.")
    second = call("POST", "/auth/login", payload={"email": owner, "password": SMOKE_PASSWORD})
    third = call("POST", "/auth/login", payload={"email": owner, "password": SMOKE_PASSWORD})
    sessions = call("GET", "/auth/sessions", token)
    if len(sessions) != 3 or sum(item["current"] for item in sessions) != 1:
        raise SmokeFailure("Active session cap or current-session identity failed.")
    call("DELETE", "/auth/sessions/" + second["session_id"], token, password, 204)
    call("GET", "/users/me", second["access_token"], status=401)
    call("GET", "/users/me", third["access_token"])
    call("POST", "/auth/sessions/revoke-others", token, password, 204)
    call("GET", "/users/me", third["access_token"], status=401)
    call("POST", "/auth/logout", foreign_token, status=204)
    call("GET", "/users/me", foreign_token, status=401)
    changed = "synthetic-replacement-password-123"
    call("PUT", "/auth/password", token, {"current_password": SMOKE_PASSWORD, "new_password": changed}, 204)
    call("GET", "/users/me", token, status=401)
    replacement = call("POST", "/auth/login", payload={"email": owner, "password": changed})
    call("POST", "/auth/logout", replacement["access_token"], status=204)
    call("GET", "/users/me", replacement["access_token"], status=401)
    log_ok("Owner backfill/create, email-bound invites, viewer/recruiter boundaries, access audit and session revocation")


async def main():
    run_id = uuid4().hex
    owner, outsider = f"ui-owner-{run_id}@example.com", f"ui-outsider-{run_id}@example.com"
    slug = f"ui-smoke-{run_id}"
    try:
        verify_shell()
        verify_workflow(owner, outsider, slug)
    finally:
        try:
            await cleanup_application_rows(slug)
        finally:
            try:
                await cleanup_candidate_rows(slug)
            finally:
                await cleanup_smoke_data(organization_slug=slug, user_emails=(owner, outsider))
    log_ok("Only this smoke's random-ID fixture rows cleaned")
    print("[success] Recruiter UI real-stack HTTP contracts passed; this is not browser automation.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
