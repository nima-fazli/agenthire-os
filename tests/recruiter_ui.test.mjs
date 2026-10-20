import test from "node:test";
import assert from "node:assert/strict";
import { ApiClient, ApiError } from "../app/web/assets/api.mjs";
import { RequestGate } from "../app/web/assets/requests.mjs";
import { Session, orgPath, jobPath } from "../app/web/assets/session.mjs";
import { sourceParts, sourceView } from "../app/web/assets/dom.mjs";
import { profilePayload } from "../app/web/assets/profiles.mjs";
import { validatePdf } from "../app/web/assets/evidence.mjs";
import { installDOM, pageResponse } from "./helpers/recruiter_dom.mjs";

const id = "11111111-1111-4111-8111-111111111111";
const foreign = "22222222-2222-4222-8222-222222222222";
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

test("private API requests omit cookies and refuse redirects and caches", async () => {
  const client = new ApiClient(() => "token", () => {}, async (path, options) => {
    assert.equal(path, "/organizations");
    assert.equal(options.headers.Authorization, "Bearer token");
    assert.equal(options.credentials, "omit"); assert.equal(options.redirect, "error"); assert.equal(options.cache, "no-store");
    return json([]);
  });
  assert.deepEqual(await client.request("/organizations"), []);
});
test("public login sends JSON without authorization", async () => {
  const client = new ApiClient(() => null, () => assert.fail(), async (_path, options) => {
    assert.equal(options.headers.Authorization, undefined);
    assert.equal(options.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(options.body), { email: "a@example.com", password: "private" });
    return json({ access_token: "a.b.c", session_id: "99999999-9999-4999-8999-999999999999", expires_at: new Date(Date.now() + 1800000).toISOString() });
  });
  await client.request("/auth/login", { method: "POST", data: { email: "a@example.com", password: "private" } });
});
for (const path of ["https://foreign.test", "//foreign.test", "/\\foreign.test", "/\t/foreign.test", "/auth/login\n", "/auth/login#token"]) {
  test(`unsafe transport path is rejected: ${JSON.stringify(path)}`, async () => {
    const client = new ApiClient(() => "secret", () => {}, () => assert.fail("transport must not run"));
    await assert.rejects(client.request(path), /INVALID_API_PATH/);
  });
}
test("current-session 401 clears the session and does not echo response text", async () => {
  let cleared = 0;
  const client = new ApiClient(() => "old", () => cleared++, async () => json({ error: { code: "EXPIRED", message: "PRIVATE_RESUME" } }, 401));
  await assert.rejects(client.request("/users/me"), error => error.status === 401 && !error.message.includes("PRIVATE_RESUME"));
  assert.equal(cleared, 1);
});
test("old-token 401 cannot clear a replacement session", async () => {
  let token = "old";
  const client = new ApiClient(() => token, () => assert.fail(), async () => { token = "new"; return json({}, 401); });
  await assert.rejects(client.request("/users/me"), ApiError);
});
test("provider failure is shown without automatic retry or lexical fallback", async () => {
  let calls = 0;
  const client = new ApiClient(() => null, () => {}, async () => { calls++; return json({ error: { code: "EXPLANATION_PROVIDER_BUSY" } }, 503); });
  await assert.rejects(client.request("/organizations"), error => error.status === 503 && error.message.includes("busy"));
  assert.equal(calls, 1);
});
test("whole response body obeys cancellation and deadline", async () => {
  const client = new ApiClient(() => null, () => {}, async (_path, { signal }) => ({
    ok: true, status: 200,
    json: () => new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("stopped", "AbortError")), { once: true })),
  }));
  await assert.rejects(client.request("/users/me", { timeout: 15 }), error => error.code === "CLIENT_TIMEOUT");
});
test("an already aborted signal reaches transport as aborted", async () => {
  const controller = new AbortController(); controller.abort();
  const client = new ApiClient(() => null, () => {}, async (_path, { signal }) => {
    assert.equal(signal.aborted, true); throw new DOMException("stopped", "AbortError");
  });
  await assert.rejects(client.request("/users/me", { signal: controller.signal }), { name: "AbortError" });
});
test("body cancellation is preserved as AbortError", async () => {
  const controller = new AbortController();
  const client = new ApiClient(() => null, () => {}, async (_path, { signal }) => ({
    ok: true, status: 200,
    json: () => new Promise((_resolve, reject) => { signal.addEventListener("abort", () => reject(new DOMException("stopped", "AbortError")), { once: true }); controller.abort(); }),
  }));
  await assert.rejects(client.request("/users/me", { signal: controller.signal }), { name: "AbortError" });
});
test("unknown error codes cannot expose inherited object properties", () => {
  const error = new ApiError(503, "constructor");
  assert.equal(error.code, "HTTP_ERROR"); assert.equal(error.message.includes("function"), false);
});
test("PDF upload uses raw bytes and PDF download rejects non-PDF content", async () => {
  const blob = new Blob(["%PDF-1.4"], { type: "application/pdf" });
  const client = new ApiClient(() => "token", () => {}, async (_path, options) => {
    if (options.method === "POST") { assert.equal(options.body, blob); assert.equal(options.headers["Content-Type"], "application/pdf"); return json({}); }
    return json({});
  });
  await client.request("/organizations", { method: "POST", body: blob });
  await assert.rejects(client.request("/organizations", { blob: true }), error => error.code === "INVALID_RESPONSE");
});
test("replaced reads discard late results even when transport ignores abort", async () => {
  const gate = new RequestGate(), old = deferred();
  const first = gate.run("source", () => old.promise);
  const rejected = assert.rejects(first, { name: "AbortError" });
  assert.equal(await gate.run("source", () => "current"), "current");
  old.resolve("old organization text"); await rejected;
});
test("context reset discards late errors as well as successes", async () => {
  const gate = new RequestGate(), old = deferred();
  const first = gate.run("explanation", () => old.promise);
  const rejected = assert.rejects(first, { name: "AbortError" });
  gate.reset(); old.reject(new ApiError(503, "PRIVATE_OLD_ERROR")); await rejected;
  assert.equal(gate.has("explanation"), false);
});
test("cancelled explanation cannot overwrite a new request", async () => {
  const gate = new RequestGate(), old = deferred();
  const first = gate.run("explanation", () => old.promise);
  const rejected = assert.rejects(first, { name: "AbortError" });
  gate.cancel("explanation");
  assert.equal(await gate.run("explanation", async () => "new"), "new");
  old.resolve("old"); await rejected;
});
test("duplicate writes are rejected without cancelling the accepted write", async () => {
  const gate = new RequestGate(), pending = deferred();
  const first = gate.run("save", () => pending.promise, false);
  await assert.rejects(gate.run("save", () => assert.fail(), false), /REQUEST_BUSY/);
  pending.resolve("stored"); assert.equal(await first, "stored");
});
test("session keeps token private and clears tenant and candidate state", () => {
  const session = new Session(); session.authenticate("a.b.c"); session.identify({ id, email: "a@example.com" });
  session.selectOrganization({ id }); session.selectJob({ id, organization_id: id }); session.selectCandidate({ id, organization_id: id });
  assert.equal(JSON.stringify(session), "{}");
  session.selectOrganization({ id: foreign }); assert.equal(session.job, null); assert.equal(session.candidate, null);
  session.clear(); assert.equal(session.token, null); assert.equal(session.organization, null); assert.equal(session.user, null);
});
test("foreign records and non-UUID path input are rejected", () => {
  const session = new Session(); session.selectOrganization({ id });
  assert.throws(() => session.selectCandidate({ id, organization_id: foreign }), /INVALID_SCOPE/);
  assert.throws(() => session.selectJob({ id, organization_id: foreign }), /INVALID_SCOPE/);
  for (const value of ["../private", `${id}?token=secret`, "<script>"]) assert.throws(() => orgPath(value));
  assert.equal(jobPath(id, foreign), `/organizations/${id}/jobs/${foreign}`);
});
const hit = { text: "A😀تجربه Python", document_id: id, chunk_set_id: foreign, chunk_position: 0, start_offset: 100,
  chunk_sha256: "a".repeat(64), source_text_sha256: "b".repeat(64), source_document_sha256: "c".repeat(64), filename: "resume.pdf" };
const citation = { ...hit, start_offset: 102, end_offset: 107, quote: "تجربه" };
test("quote rendering uses Unicode code points and absolute source offsets", () => {
  assert.deepEqual(sourceParts(hit, citation), ["A😀", "تجربه", " Python"]);
});
test("fabricated quotes, foreign source and mismatched provenance fail closed", () => {
  for (const patch of [{ quote: "Rust" }, { document_id: foreign }, { start_offset: 101 }, { end_offset: 999 }, { chunk_sha256: "d".repeat(64) }])
    assert.throws(() => sourceParts(hit, { ...citation, ...patch }), /INVALID_CITATION/);
});
test("hostile source text is inserted as text, never HTML", () => {
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.value = ""; }
    set textContent(value) { this.value = value; }
    get textContent() { return this.value + this.children.map(child => child.textContent).join(""); }
    set innerHTML(_value) { assert.fail("HTML injection sink"); }
    append(...children) { this.children.push(...children); }
  }
  const oldDocument = globalThis.document;
  globalThis.document = { createElement: tag => new Element(tag), createTextNode: text => { const value = new Element("#text"); value.textContent = text; return value; } };
  try {
    const payload = '<img src=x onerror="steal()"><script>secret</script>';
    const result = sourceView({ ...hit, text: payload, filename: payload });
    assert.ok(result.textContent.includes(payload));
    const tags = element => [element.tag, ...element.children.flatMap(tags)];
    assert.equal(tags(result).includes("img"), false); assert.equal(tags(result).includes("script"), false);
  } finally { globalThis.document = oldDocument; }
});
test("criterion payload preserves server keys and rejects empty or duplicate rows", () => {
  const row = { key: "python", label: " Python ", q: " Python ", importance: "required" };
  assert.deepEqual(profilePayload([row]), { criteria: [{ key: "python", label: "Python", q: "Python", importance: "required" }] });
  for (const rows of [[], [row, row], [{ ...row, q: " " }], [{ ...row, importance: "hire" }]]) assert.throws(() => profilePayload(rows), ApiError);
});
test("client PDF bounds reject paths, empty files and oversized content", () => {
  assert.equal(validatePdf({ name: "Resume.PDF", size: 5 }).size, 5);
  for (const file of [null, { name: ".pdf", size: 2 }, { name: "x\u202e.pdf", size: 2 }, { name: "x.txt", size: 2 }, { name: "../x.pdf", size: 2 }, { name: "x.pdf", size: 0 }, { name: "x.pdf", size: 10485761 }])
    assert.throws(() => validatePdf(file), ApiError);
});
test("controller handles stale selections, cancelled writes, failed profiles and expired sessions", async () => {
  const dom = installDOM(), { elements } = dom;
  const nextJob = "55555555-5555-4555-8555-555555555555", failedJob = "66666666-6666-4666-8666-666666666666";
  const nextCandidate = "77777777-7777-4777-8777-777777777777";
  const job = "33333333-3333-4333-8333-333333333333", candidate = "44444444-4444-4444-8444-444444444444";
  const record = { id: candidate, organization_id: id, full_name: "داوطلب مصنوعی", headline: "Python" };
  const otherRecord = { ...record, id: nextCandidate, full_name: "داوطلب دوم" };
  const pending = deferred(), saving = deferred(), reading = deferred();
  let expired = false, started = false, saveStarted = false, readStarted = false;
  globalThis.fetch = async (path, options) => {
    if (path === "/auth/login") return json({ access_token: "a.b.c",
      session_id: "99999999-9999-4999-8999-999999999999", expires_at: new Date(Date.now() + 1800000).toISOString() });
    assert.equal(options.headers.Authorization, "Bearer a.b.c");
    if (expired) return json({ error: { code: "EXPIRED" } }, 401);
    if (path === "/auth/logout") return new Response(null, { status: 204 });
    if (path.includes("/access?")) return json({
      organization_id: path.split("/")[2], role: "owner", can_write: true, can_manage: true,
      members: [], invitations: [], events: [], offset: 0, has_more: false,
    });
    if (path === "/users/me") return json({ id, email: "fixture@example.com" });
    if (path.startsWith("/organizations/page?")) return pageResponse([{ id, name: "Organization الف" }, { id: foreign, name: "Organization ب" }], path);
    if (path.startsWith(`${orgPath(id)}/recruiting/jobs?`)) return pageResponse([job, nextJob, failedJob].map(value => ({ id: value, organization_id: id, title: "Backend", description: "Synthetic" })), path);
    if (path.startsWith(`${orgPath(id)}/recruiting/candidates?`)) return pageResponse([record, otherRecord], path);
    if (path.includes("/recruiting/applications?")) return pageResponse([], path);
    if (path === `${orgPath(id)}/candidates/${candidate}`) { readStarted = true; return reading.promise; }
    if (path.includes("/candidate-retrieval?")) return json({ job_id: job, total: 1, items: [{ ...hit, candidate_id: candidate, candidate_name: record.full_name, score: 0.7 }] });
    if (path === `${jobPath(id, job)}/match-profile` && options.method === "PUT") { saveStarted = true; return saving.promise; }
    if (path.startsWith(jobPath(id, failedJob))) return json({ error: { code: "HTTP_ERROR" } }, 503);
    if (path.startsWith(orgPath(foreign))) return pageResponse([], path);
    if (path.endsWith("/match-profile")) return json({ job_id: path.split("/jobs/")[1].split("/")[0], revision: 1, criteria: [{ key: "python", label: "Python", q: "Python", importance: "required" }] });
    if (path.endsWith("/search-profile")) return json({ job_id: path.split("/jobs/")[1].split("/")[0], revision: 1, q: "Python" });
    if (path.includes("/documents?")) return json([]);
    if (path.endsWith("/grounded-explanation")) { started = true; return pending.promise; }
    throw new Error(`Unexpected fixture path: ${path}`);
  };
  const wait = dom.wait;
  try {
    await import("../app/web/assets/app.mjs");
    elements.get("auth-email").value = "fixture@example.com"; elements.get("auth-password").value = "synthetic-password";
    elements.get("auth-form").emit("submit");
    await wait(() => elements.get("candidate-list").textContent.includes(record.full_name) && elements.get("profiles-fields").disabled === false);
    assert.equal(elements.get("shell").hidden, false);
    const visit = element => [element, ...element.children.flatMap(visit)];
    visit(elements.get("candidate-list")).find(item => item.tag === "button").emit("click");
    await wait(() => elements.get("candidate-fields").disabled === false);
    elements.get("retrieval-mode").value = "lexical"; elements.get("retrieval-form").emit("submit");
    await wait(() => visit(elements.get("retrieval-results")).some(item => item.tag === "button"));
    visit(elements.get("retrieval-results")).find(item => item.tag === "button").emit("click");
    await wait(() => readStarted);
    visit(elements.get("candidate-list")).filter(item => item.tag === "button")[1].emit("click");
    await wait(() => elements.get("candidate-heading").textContent.includes(otherRecord.full_name));
    reading.resolve(json(record)); await new Promise(resolve => setTimeout(resolve, 5));
    assert.ok(elements.get("candidate-heading").textContent.includes(otherRecord.full_name));
    elements.get("match-profile-form").emit("submit"); await wait(() => saveStarted);
    assert.equal(elements.get("match-save").disabled, true);
    elements.get("job-select").value = nextJob; elements.get("job-select").emit("change");
    await wait(() => elements.get("profiles-fields").disabled === false);
    assert.equal(elements.get("match-save").disabled, false);
    saving.resolve(json({ job_id: job, revision: 99 })); await new Promise(resolve => setTimeout(resolve, 5));
    assert.equal(elements.get("match-revision").textContent.includes("99"), false);
    elements.get("job-select").value = failedJob; elements.get("job-select").emit("change");
    await wait(() => elements.get("notice").className.includes("error"));
    assert.equal(elements.get("profiles-fields").disabled, true);
    assert.equal(elements.get("retrieval-run").disabled, true);
    elements.get("job-select").value = job; elements.get("job-select").emit("change");
    await wait(() => elements.get("profiles-fields").disabled === false);
    elements.get("explanation-run").emit("click"); await wait(() => started);
    elements.get("organization-select").value = foreign; elements.get("organization-select").emit("change");
    await wait(() => elements.get("organization-heading").textContent === "Organization ب");
    pending.resolve(json({ job_id: job, candidate_id: candidate, summary_text: "OLD-PRIVATE-TEXT", summary: {}, criteria: [] }));
    await new Promise(resolve => setTimeout(resolve, 5));
    assert.equal(elements.get("evidence-results").textContent.includes("OLD-PRIVATE-TEXT"), false);
    assert.equal(elements.get("candidate-heading").textContent.includes(record.full_name), false);
    expired = true; elements.get("workspace-refresh").emit("click");
    await wait(() => elements.get("shell").hidden === true);
    assert.equal(elements.get("account-email").textContent, "");
    assert.equal(elements.get("auth-password").value, "");
    assert.equal(elements.get("candidate-list").textContent.includes(record.full_name), false);
  } finally {
    await dom.restore();
  }
});


test("request deadline also bounds a transport that ignores abort", async () => {
  const client = new ApiClient(() => null, () => {}, () => new Promise(() => {}));
  await assert.rejects(client.request("/users/me", { timeout: 15 }), error => error.code === "CLIENT_TIMEOUT");
});
test("late unauthorized response after timeout cannot clear a session", async () => {
  const response = deferred(); let cleared = 0;
  const client = new ApiClient(() => "current", () => cleared++, () => response.promise);
  await assert.rejects(client.request("/users/me", { timeout: 15 }), error => error.code === "CLIENT_TIMEOUT");
  response.resolve(json({}, 401)); await new Promise(resolve => setTimeout(resolve, 1));
  assert.equal(cleared, 0);
});
test("oversized streaming JSON is cancelled and never exposed", async () => {
  let cancelled = false;
  const stream = new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array(2 * 1024 * 1024 + 1)); },
    cancel() { cancelled = true; },
  });
  const client = new ApiClient(() => null, () => {}, async () => new Response(stream, { headers: { "Content-Type": "application/json" } }));
  await assert.rejects(client.request("/users/me"), error => error.code === "INVALID_RESPONSE");
  assert.equal(cancelled, true);
});
test("wrong source bounds are rejected before rendering", () => {
  for (const patch of [{ end_offset: 999 }, { chunk_position: -1 }, { start_offset: "100" }, { source_text_sha256: "invalid" }])
    assert.throws(() => sourceParts({ ...hit, ...patch }), /INVALID_SOURCE/);
});
test("session snapshots cannot be changed through the input record", () => {
  const session = new Session(), item = { id };
  session.selectOrganization(item); item.id = foreign;
  assert.equal(session.organization.id, id); assert.equal(Object.isFrozen(session.organization), true);
});
test("unsafe method, ambiguous body and encoded path are rejected", async () => {
  const client = new ApiClient(() => null, () => {}, () => assert.fail());
  await assert.rejects(client.request("/users/me", { method: "TRACE" }), /INVALID_API_REQUEST/);
  await assert.rejects(client.request("/users/me", { data: {}, body: new Blob() }), /INVALID_API_REQUEST/);
  await assert.rejects(client.request("/organizations/%2f%2fforeign.test"), /INVALID_API_PATH/);
});
test("criterion input and PDF size types fail closed", () => {
  for (const rows of [null, [null], [{ key: "python", label: 4, q: "Python" }]]) assert.throws(() => profilePayload(rows), ApiError);
  assert.throws(() => validatePdf({ name: "resume.pdf", size: NaN }), ApiError);
});
