import test from "node:test";
import assert from "node:assert/strict";
import { scenario, ids } from "./helpers/recruiter_scenario.mjs";
import { json } from "./helpers/recruiter_dom.mjs";
import { sourceParts } from "../app/web/assets/dom.mjs";
import { validatePage } from "../app/web/assets/paging.mjs";

test("candidate search and paging query the server and preserve the selected job", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    e.get("candidate-next").click();
    await wait(() => e.get("candidate-page-info").textContent.includes("21 to 24"));
    assert.equal(e.get("job-select").value, ids.job);
    e.get("candidate-filter").value = "Candidate 23"; e.get("candidate-search-form").emit("submit");
    await wait(() => e.get("candidate-page-info").textContent === "1 to 1 of 1 results");
    assert.ok(state.calls.some(item => item.path.includes("offset=20")));
    assert.ok(state.calls.some(item => item.path.includes("q=Candidate+23") && item.path.includes("offset=0")));
    assert.equal(state.calls.some(item => item.method === "GET" && item.path === `/organizations/${ids.org}/candidates`), false);
  } finally { await f.close(); }
});

test("a superseded server search cannot restore its old results", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    let finish;
    state.intercept = path => path.includes("q=slow") ? new Promise(resolve => { finish = resolve; }) : undefined;
    e.get("candidate-filter").value = "slow"; e.get("candidate-search-form").emit("submit");
    await wait(() => Boolean(finish));
    e.get("candidate-filter").value = "Candidate 23"; e.get("candidate-search-form").emit("submit");
    await wait(() => e.get("candidate-page-info").textContent === "1 to 1 of 1 results");
    finish(json({ items: [{ ...state.candidates[0], full_name: "LATE_PRIVATE" }], total: 1, limit: 20, offset: 0 }));
    await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(e.get("candidate-list").textContent.includes("LATE_PRIVATE"), false);
  } finally { await f.close(); }
});

test("candidate editing clears optional fields and keeps a draft after a version conflict", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    await f.selectCandidate();
    e.get("candidate-edit-full_name").value = "Renamed"; e.get("candidate-edit-email").value = "";
    e.get("candidate-edit-form").emit("submit");
    await wait(() => e.get("notice").textContent === "Candidate updated.");
    const write = state.calls.find(item => item.method === "PUT");
    assert.equal(write.data.email, null);
    assert.equal(write.data.expected_updated_at, "2026-01-01T00:00:00Z");
    state.candidates[0].updated_at = "2026-01-03T00:00:00Z";
    e.get("candidate-edit-full_name").value = "Overwrite"; e.get("candidate-edit-form").emit("submit");
    await wait(() => e.get("notice").textContent.includes("concurrently"));
    assert.equal(state.candidates[0].full_name, "Renamed");
    assert.equal(e.get("candidate-edit-full_name").value, "Overwrite");
    e.get("candidate-edit-refresh").click();
    await wait(() => e.get("candidate-edit-full_name").value === "Renamed");
  } finally { await f.close(); }
});

test("job editing uses the versioned endpoint and preserves the current selection", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    e.get("job-edit-title").value = "Staff Engineer"; e.get("job-edit-status").value = "open";
    e.get("job-edit-form").emit("submit");
    await wait(() => e.get("notice").textContent === "Job updated.");
    assert.equal(state.jobs[0].status, "open");
    assert.equal(e.get("job-select").value, ids.job);
    assert.ok(e.get("job-description-view").textContent.includes("Staff Engineer"));
    assert.ok(state.calls.some(item => item.method === "PUT" && item.path.endsWith(`/recruiting/jobs/${ids.job}`)));
  } finally { await f.close(); }
});

test("application creation, duplicate feedback and an explicitly confirmed transition work together", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    await f.selectCandidate(); e.get("application-create").click();
    await wait(() => e.get("notice").textContent === "Application created.");
    e.get("application-create").click();
    await wait(() => e.get("notice").textContent.includes("already applied for this job"));
    assert.equal(state.applications.length, 1);
    const card = e.get("application-list").children[0].children[0];
    const select = card.children.find(item => item.tag === "label").children[1];
    select.value = "screening"; select.emit("change");
    f.button("application-list", "Update status").click();
    await wait(() => e.get("confirm-dialog").open);
    assert.equal(state.calls.filter(item => item.path.endsWith("/transitions")).length, 0);
    e.get("confirm-cancel").click();
    assert.equal(state.applications[0].status, "applied");
    f.button("application-list", "Update status").click();
    e.get("confirm-form").emit("submit");
    await wait(() => e.get("notice").textContent === "Status updated.");
    assert.equal(state.applications[0].status, "screening");
    state.applications[0].status = "hired"; e.get("application-refresh").click();
    await wait(() => e.get("application-list").textContent.includes("terminal state"));
    assert.equal(f.button("application-list", "Update status"), undefined);
  } finally { await f.close(); }
});

test("PDF deletion requires the exact filename and sends only one scoped DELETE", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    await f.selectCandidate(); f.button("documents-list", "Delete PDF").click();
    await wait(() => e.get("confirm-dialog").open);
    e.get("confirm-input").value = "wrong.pdf"; e.get("confirm-input").emit("input");
    e.get("confirm-form").emit("submit");
    assert.equal(state.calls.some(item => item.method === "DELETE"), false);
    assert.equal(e.get("confirm-accept").disabled, true);
    e.get("confirm-input").value = "synthetic.pdf"; e.get("confirm-input").emit("input");
    e.get("confirm-form").emit("submit");
    await wait(() => e.get("notice").textContent === "Resume deleted.");
    const writes = state.calls.filter(item => item.method === "DELETE");
    assert.equal(writes.length, 1);
    assert.ok(writes[0].path.endsWith(`/documents/${ids.document}`));
    assert.equal(state.documents.length, 0);
  } finally { await f.close(); }
});

test("changing organizations cancels an open deletion confirmation", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    await f.selectCandidate(); f.button("documents-list", "Delete PDF").click();
    await wait(() => e.get("confirm-dialog").open);
    e.get("organization-select").value = ids.other; e.get("organization-select").emit("change");
    await wait(() => e.get("organization-heading").textContent === "Other organization");
    e.get("confirm-form").emit("submit");
    assert.equal(e.get("confirm-dialog").open, false);
    assert.equal(state.calls.some(item => item.method === "DELETE"), false);
    assert.equal(e.get("documents-list").textContent, "");
  } finally { await f.close(); }
});

test("embedding controls refresh status and retry only after an explicit click", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    await f.selectCandidate(); f.button("documents-list", "Start / view embeddings").click();
    await wait(() => e.get("documents-list").textContent.includes("Embeddings: Queued"));
    const posts = () => state.calls.filter(item => item.method === "POST" && item.path.endsWith("/embedding-jobs"));
    assert.equal(posts().length, 1); assert.equal(posts()[0].data.retry, false);
    state.embedding.status = "failed"; f.button("documents-list", "Refresh embedding status").click();
    await wait(() => e.get("documents-list").textContent.includes("Embeddings: Failed"));
    assert.equal(posts().length, 1);
    f.button("documents-list", "Start / view embeddings").click();
    await wait(() => posts().length === 2 && e.get("documents-list").textContent.includes("attempt 2"));
    assert.equal(posts()[1].data.retry, true);
  } finally { await f.close(); }
});

test("disabled semantic processing has safe feedback and is never retried automatically", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    state.semanticDisabled = true;
    await f.selectCandidate(); f.button("documents-list", "Start / view embeddings").click();
    await wait(() => e.get("notice").textContent.includes("is disabled"));
    assert.equal(state.calls.filter(item => item.path.endsWith("/embedding-jobs")).length, 1);
    assert.equal(e.get("notice").textContent.includes("PRIVATE_SERVER_TEXT"), false);
  } finally { await f.close(); }
});

test("a late edit response cannot repopulate a different organization", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    await f.selectCandidate();
    let finish;
    state.intercept = (_path, options) => options.method === "PUT" ? new Promise(resolve => { finish = resolve; }) : undefined;
    e.get("candidate-edit-full_name").value = "Late"; e.get("candidate-edit-form").emit("submit");
    await wait(() => Boolean(finish));
    e.get("organization-select").value = ids.other; e.get("organization-select").emit("change");
    finish(json({ ...state.candidates[0], full_name: "LATE_PRIVATE" }));
    await wait(() => e.get("organization-heading").textContent === "Other organization");
    await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(e.get("candidate-edit-full_name").value, "");
    assert.equal(e.get("candidate-heading").textContent.includes("LATE_PRIVATE"), false);
  } finally { await f.close(); }
});

test("an expired page request clears selected private data", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    await f.selectCandidate(); state.expired = true;
    e.get("candidate-search-form").emit("submit");
    await wait(() => e.get("shell").hidden);
    assert.equal(e.get("candidate-edit-email").value, "");
    assert.equal(e.get("documents-list").textContent, "");
    assert.equal(e.get("account-email").textContent, "");
  } finally { await f.close(); }
});

test("complete assigned quote context supports 4000 Unicode code points", () => {
  const hit = { text: "😀".repeat(4000), document_id: ids.document, chunk_set_id: ids.job,
    chunk_position: 0, start_offset: 10, end_offset: 4010, chunk_sha256: "a".repeat(64),
    source_text_sha256: "b".repeat(64), source_document_sha256: "c".repeat(64) };
  assert.deepEqual(sourceParts(hit, { ...hit, quote: hit.text }), ["", hit.text, ""]);
  assert.throws(() => sourceParts({ ...hit, text: hit.text + "x", end_offset: 4011 }), /INVALID_SOURCE/);
});

test("page envelopes reject malformed totals and mismatched requested offsets", () => {
  for (const page of [{ items: [], total: -1, limit: 20, offset: 0 },
    { items: [], total: 0, limit: 100, offset: 0 }, { items: [], total: 0, limit: 20, offset: 20 }])
    assert.throws(() => validatePage(page, 0));
});

test("viewer keeps reading controls and cannot send recruiting mutations", async () => {
  const f = await scenario({ role: "viewer" });
  try {
    const { elements: e, state } = f;
    assert.equal(e.get("access-owner").hidden, true);
    assert.equal(e.get("job-create").disabled, true);
    assert.equal(e.get("job-edit-fields").disabled, true);
    assert.equal(e.get("profiles-fields").disabled, true);
    assert.equal(e.get("retrieval-run").disabled, false);
    await f.selectCandidate();
    assert.equal(e.get("document-upload").disabled, true);
    assert.equal(f.button("documents-list", "Delete PDF").disabled, true);
    assert.equal(f.button("documents-list", "Start / view embeddings").disabled, true);
    assert.equal(f.button("documents-list", "Download PDF").disabled, false);
    e.get("candidate-edit-form").emit("submit");
    e.get("application-create").click();
    await new Promise(resolve => setTimeout(resolve, 5));
    assert.equal(state.calls.some(item => ["PUT", "DELETE"].includes(item.method)), false);
    assert.equal(e.get("shell").hidden, false);
  } finally { await f.close(); }
});

test("recruiter can edit without receiving the owner's member and invitation lists", async () => {
  const f = await scenario({ role: "recruiter" });
  try {
    const { elements: e, state, wait } = f;
    assert.equal(e.get("access-owner").hidden, true);
    assert.equal(e.get("access-members").textContent, "");
    e.get("job-edit-title").value = "Authorized edit"; e.get("job-edit-form").emit("submit");
    await wait(() => state.jobs[0].title === "Authorized edit");
    assert.equal(e.get("job-edit-fields").disabled, true);
    await wait(() => !e.get("job-edit-fields").disabled);
  } finally { await f.close(); }
});

test("invitation creation clears the password, waits for confirmation and exposes the code once", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    e.get("invitation-email").value = "invited@example.com"; e.get("invitation-role").value = "viewer";
    e.get("access-password").value = state.password; e.get("invitation-form").emit("submit");
    await wait(() => e.get("confirm-dialog").open);
    assert.equal(e.get("access-password").value, "");
    assert.equal(state.invitations.length, 0);
    e.get("confirm-form").emit("submit");
    await wait(() => e.get("invitation-secret").value.length === 43 && !e.get("access-owner-fields").disabled);
    assert.equal(state.invitations[0].role, "viewer");
    assert.equal(state.calls.some(item => item.path.includes("a".repeat(43))), false);
    e.get("access-password").value = state.password; f.button("access-invitations", "Revoke invitation").click();
    await wait(() => e.get("confirm-dialog").open); e.get("confirm-form").emit("submit");
    await wait(() => state.invitations.length === 0 && !e.get("access-owner-fields").disabled);
    e.get("organization-select").value = ids.other; e.get("organization-select").emit("change");
    await wait(() => e.get("organization-heading").textContent === "Other organization");
    assert.equal(e.get("invitation-secret").value, "");
  } finally { await f.close(); }
});

test("owner role changes use a confirmed expected role and stale roles are not overwritten", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    const card = e.get("access-members").children[0].children[1];
    const choice = card.children.find(item => item.tag === "label").children[1];
    choice.value = "recruiter"; choice.emit("change");
    e.get("access-password").value = state.password;
    card.children.find(item => item.tag === "button" && item.textContent === "Change role").click();
    await wait(() => e.get("confirm-dialog").open);
    state.members[1].role = "owner";
    e.get("confirm-form").emit("submit");
    await wait(() => e.get("notice").textContent.includes("has changed"));
    const write = state.calls.find(item => item.method === "PUT" && item.path.includes("/access/members/"));
    assert.equal(write.data.expected_role, "viewer");
    assert.equal(write.data.role, "recruiter");
    assert.equal(state.members[1].role, "owner");
    assert.equal(e.get("shell").hidden, false);
  } finally { await f.close(); }
});

test("wrong confirmation password does not log out a valid session or expose server text", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    e.get("sessions-refresh").click();
    await wait(() => Boolean(f.button("sessions-list", "Revoke session")));
    e.get("account-password").value = "wrong";
    f.button("sessions-list", "Revoke session").click();
    await wait(() => e.get("confirm-dialog").open); e.get("confirm-form").emit("submit");
    await wait(() => e.get("notice").textContent.includes("current password"));
    assert.equal(state.sessions.length, 2);
    assert.equal(e.get("shell").hidden, false);
    assert.equal(e.get("account-password").value, "");
    assert.equal(e.get("notice").textContent.includes("PRIVATE_SERVER_TEXT"), false);
  } finally { await f.close(); }
});

test("session revocation is scoped, confirmed and refreshes active session metadata", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    e.get("sessions-refresh").click();
    await wait(() => Boolean(f.button("sessions-list", "Revoke session")));
    e.get("account-password").value = state.password;
    e.get("sessions-revoke-others").click();
    await wait(() => e.get("confirm-dialog").open);
    e.get("confirm-cancel").click(); await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(state.sessions.length, 2);
    e.get("account-password").value = state.password;
    f.button("sessions-list", "Revoke session").click();
    await wait(() => e.get("confirm-dialog").open); e.get("confirm-form").emit("submit");
    await wait(() => state.sessions.length === 1 && !e.get("account-fields").disabled);
    assert.equal(state.sessions[0].current, true);
    assert.equal(f.button("sessions-list", "Revoke session"), undefined);
    assert.equal(e.get("account-password").value, "");
  } finally { await f.close(); }
});

test("password change confirms, sends secrets only in the body and clears the workspace", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    await f.selectCandidate();
    e.get("account-password").value = state.password;
    e.get("account-new-password").value = e.get("account-confirm-password").value = "new-synthetic-password";
    e.get("password-form").emit("submit");
    await wait(() => e.get("confirm-dialog").open);
    assert.equal(e.get("account-new-password").value, "");
    assert.equal(e.get("account-confirm-password").value, "");
    assert.equal(state.password, "synthetic-password");
    e.get("confirm-form").emit("submit");
    await wait(() => e.get("shell").hidden);
    assert.equal(state.password, "new-synthetic-password");
    assert.equal(e.get("documents-list").textContent, "");
    assert.equal(e.get("access-members").textContent, "");
    assert.equal(e.get("account-password").value, "");
    const call = state.calls.find(item => item.path === "/auth/password");
    assert.equal(call.data.new_password, "new-synthetic-password");
    assert.equal(state.calls.some(item => item.path.includes("synthetic-password")), false);
  } finally { await f.close(); }
});

test("logout submits server revocation and clears a selected private record immediately", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    await f.selectCandidate();
    let finish;
    state.intercept = path => path === "/auth/logout" ? new Promise(resolve => { finish = resolve; }) : undefined;
    e.get("logout").click();
    assert.equal(e.get("shell").hidden, true);
    assert.equal(e.get("candidate-edit-email").value, "");
    assert.equal(e.get("access-members").textContent, "");
    await wait(() => Boolean(finish));
    assert.equal(state.calls.filter(item => item.path === "/auth/logout").length, 1);
    finish(new Response(null, { status: 204 }));
  } finally { await f.close(); }
});

test("a late owner access response cannot fill a different organization's member list", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    let finish;
    state.intercept = path => path.startsWith("/organizations/" + ids.org + "/access?")
      ? new Promise(resolve => { finish = resolve; }) : undefined;
    e.get("access-refresh").click(); await wait(() => Boolean(finish));
    e.get("organization-select").value = ids.other; e.get("organization-select").emit("change");
    await wait(() => e.get("organization-heading").textContent === "Other organization");
    finish(json({ organization_id: ids.org, role: "owner", can_write: true, can_manage: true,
      members: [{ ...state.members[0], email: "LATE_PRIVATE" }], invitations: [], events: [], offset: 0, has_more: false }));
    await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(e.get("access-members").textContent.includes("LATE_PRIVATE"), false);
  } finally { await f.close(); }
});

test("invitation acceptance clears its secret and never includes it in a request URL", async () => {
  const f = await scenario({ role: "viewer" });
  try {
    const { elements: e, state, wait } = f;
    e.get("invitation-token").value = "z".repeat(43); e.get("invitation-accept-form").emit("submit");
    await wait(() => e.get("notice").textContent.includes("Invitation accepted"));
    assert.equal(e.get("invitation-token").value, "");
    assert.equal(state.calls.find(item => item.path === "/access/invitations/accept").data.token, "z".repeat(43));
    assert.equal(state.calls.some(item => item.path.includes("z".repeat(43))), false);
  } finally { await f.close(); }
});


test("session expiry clears the account even when no API request is in flight", async () => {
  const { installDOM } = await import("./helpers/recruiter_dom.mjs");
  const { createAccess } = await import("../app/web/assets/access.mjs");
  const dom = installDOM();
  let message = "";
  const access = createAccess({ session: {}, isPending: () => false }, value => {
    message = value; access.clearSession();
  });
  try {
    access.startSession({ session_id: ids.session, expires_at: new Date(Date.now() + 40).toISOString() });
    await dom.wait(() => Boolean(message));
    assert.equal(dom.elements.get("session-expiry").textContent, "");
  } finally { access.clearSession(); await dom.restore(); }
});
