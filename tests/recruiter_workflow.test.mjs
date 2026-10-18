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
    await wait(() => e.get("candidate-page-info").textContent.includes("21 تا 24"));
    assert.equal(e.get("job-select").value, ids.job);
    e.get("candidate-filter").value = "Candidate 23"; e.get("candidate-search-form").emit("submit");
    await wait(() => e.get("candidate-page-info").textContent === "1 تا 1 از 1 نتیجه");
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
    await wait(() => e.get("candidate-page-info").textContent === "1 تا 1 از 1 نتیجه");
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
    await wait(() => e.get("notice").textContent === "پرونده ویرایش شد.");
    const write = state.calls.find(item => item.method === "PUT");
    assert.equal(write.data.email, null);
    assert.equal(write.data.expected_updated_at, "2026-01-01T00:00:00Z");
    state.candidates[0].updated_at = "2026-01-03T00:00:00Z";
    e.get("candidate-edit-full_name").value = "Overwrite"; e.get("candidate-edit-form").emit("submit");
    await wait(() => e.get("notice").textContent.includes("هم‌زمان"));
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
    await wait(() => e.get("notice").textContent === "شغل ویرایش شد.");
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
    await wait(() => e.get("notice").textContent === "درخواست استخدام ثبت شد.");
    e.get("application-create").click();
    await wait(() => e.get("notice").textContent.includes("قبلاً برای همین شغل"));
    assert.equal(state.applications.length, 1);
    const card = e.get("application-list").children[0].children[0];
    const select = card.children.find(item => item.tag === "label").children[1];
    select.value = "screening"; select.emit("change");
    f.button("application-list", "ثبت تغییر وضعیت").click();
    await wait(() => e.get("confirm-dialog").open);
    assert.equal(state.calls.filter(item => item.path.endsWith("/transitions")).length, 0);
    e.get("confirm-cancel").click();
    assert.equal(state.applications[0].status, "applied");
    f.button("application-list", "ثبت تغییر وضعیت").click();
    e.get("confirm-form").emit("submit");
    await wait(() => e.get("notice").textContent === "وضعیت ثبت شد.");
    assert.equal(state.applications[0].status, "screening");
    state.applications[0].status = "hired"; e.get("application-refresh").click();
    await wait(() => e.get("application-list").textContent.includes("وضعیت نهایی"));
    assert.equal(f.button("application-list", "ثبت تغییر وضعیت"), undefined);
  } finally { await f.close(); }
});

test("PDF deletion requires the exact filename and sends only one scoped DELETE", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    await f.selectCandidate(); f.button("documents-list", "حذف PDF").click();
    await wait(() => e.get("confirm-dialog").open);
    e.get("confirm-input").value = "wrong.pdf"; e.get("confirm-input").emit("input");
    e.get("confirm-form").emit("submit");
    assert.equal(state.calls.some(item => item.method === "DELETE"), false);
    assert.equal(e.get("confirm-accept").disabled, true);
    e.get("confirm-input").value = "synthetic.pdf"; e.get("confirm-input").emit("input");
    e.get("confirm-form").emit("submit");
    await wait(() => e.get("notice").textContent === "رزومه حذف شد.");
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
    await f.selectCandidate(); f.button("documents-list", "حذف PDF").click();
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
    await f.selectCandidate(); f.button("documents-list", "شروع / مشاهدهٔ بردار معنایی").click();
    await wait(() => e.get("documents-list").textContent.includes("بردار معنایی: در صف"));
    const posts = () => state.calls.filter(item => item.method === "POST" && item.path.endsWith("/embedding-jobs"));
    assert.equal(posts().length, 1); assert.equal(posts()[0].data.retry, false);
    state.embedding.status = "failed"; f.button("documents-list", "تازه‌سازی وضعیت بردار").click();
    await wait(() => e.get("documents-list").textContent.includes("بردار معنایی: ناموفق"));
    assert.equal(posts().length, 1);
    f.button("documents-list", "شروع / مشاهدهٔ بردار معنایی").click();
    await wait(() => posts().length === 2 && e.get("documents-list").textContent.includes("تلاش 2"));
    assert.equal(posts()[1].data.retry, true);
  } finally { await f.close(); }
});

test("disabled semantic processing has safe feedback and is never retried automatically", async () => {
  const f = await scenario();
  try {
    const { elements: e, state, wait } = f;
    state.semanticDisabled = true;
    await f.selectCandidate(); f.button("documents-list", "شروع / مشاهدهٔ بردار معنایی").click();
    await wait(() => e.get("notice").textContent.includes("فعال نیست"));
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
