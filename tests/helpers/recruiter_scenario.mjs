import assert from "node:assert/strict";
import { installDOM, json, visit } from "./recruiter_dom.mjs";

export const ids = Object.freeze({
  org: "11111111-1111-4111-8111-111111111111",
  other: "22222222-2222-4222-8222-222222222222",
  job: "33333333-3333-4333-8333-333333333333",
  document: "44444444-4444-4444-8444-444444444444",
  application: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  embedding: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
});
const date = "2026-01-01T00:00:00Z";
const nextStatuses = { applied: ["screening", "rejected"], screening: ["interview", "rejected"],
  interview: ["offer", "rejected"], offer: ["hired", "rejected"], hired: [], rejected: [] };
let instance = 0;

export async function scenario({ count = 24 } = {}) {
  const dom = installDOM(), { elements, wait } = dom;
  const state = {
    jobs: [{ id: ids.job, organization_id: ids.org, title: "Backend", description: "Synthetic", status: "draft", updated_at: date }],
    candidates: Array.from({ length: count }, (_, i) => ({
      id: `${String(i + 10).padStart(8, "0")}-1111-4111-8111-111111111111`, organization_id: ids.org,
      full_name: `Candidate ${i}`, email: `fixture${i}@example.com`, headline: "Python", phone: null,
      location: "Synthetic", summary: null, updated_at: date,
    })),
    applications: [], documents: [], embedding: null, calls: [], unexpected: [],
    expired: false, semanticDisabled: false, intercept: null,
  };
  state.documents = [{ id: ids.document, organization_id: ids.org,
    candidate_id: state.candidates[0].id, filename: "synthetic.pdf", size_bytes: 1024 }];
  const error = (code, status = 409) => json({ error: { code, message: "PRIVATE_SERVER_TEXT" } }, status);
  globalThis.fetch = async (path, options) => {
    const url = new URL(path, "http://fixture"), resource = url.pathname;
    const method = options.method;
    const data = typeof options.body === "string" ? JSON.parse(options.body) : options.body;
    state.calls.push({ path, method, data });
    if (state.intercept) {
      const intercepted = state.intercept(path, options, data);
      if (intercepted !== undefined) return await intercepted;
    }
    if (resource === "/auth/login") return json({ access_token: "a.b.c" });
    assert.equal(options.headers.Authorization, "Bearer a.b.c");
    if (state.expired) return error("INVALID_ACCESS_TOKEN", 401);
    if (resource === "/users/me") return json({ id: ids.org, email: "fixture@example.com" });
    const page = values => {
      const q = (url.searchParams.get("q") ?? "").toLowerCase();
      const status = url.searchParams.get("status");
      const filtered = values.filter(item => (!q || [item.name, item.title, item.full_name, item.candidate_name].some(
        value => value?.toLowerCase().includes(q))) && (!status || item.status === status));
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 20);
      return json({ items: filtered.slice(offset, offset + limit), total: filtered.length, offset, limit });
    };
    if (resource === "/organizations/page") return page([
      { id: ids.org, name: "Organization" }, { id: ids.other, name: "Other organization" },
    ]);
    const route = resource.match(/^\/organizations\/([^/]+)\/recruiting\/(jobs|candidates|applications)(?:\/([^/]+))?$/);
    if (route) {
      const [, org, kind, recordId] = route;
      let values = state[kind].filter(item => item.organization_id === org);
      if (method === "PUT") {
        const record = values.find(item => item.id === recordId);
        if (!record) return error("CANDIDATE_NOT_FOUND", 404);
        if (record.updated_at !== data.expected_updated_at) return error("RECORD_CHANGED");
        const { expected_updated_at: _version, ...patch } = data;
        Object.assign(record, patch, { updated_at: "2026-01-02T00:00:00Z" });
        return json(record);
      }
      if (kind === "applications") {
        const job = url.searchParams.get("job_id");
        values = values.filter(item => !job || item.job_id === job).map(item => ({ ...item,
          candidate_name: state.candidates.find(value => value.id === item.candidate_id).full_name,
          job_title: state.jobs.find(value => value.id === item.job_id).title,
          allowed_statuses: nextStatuses[item.status],
        }));
      }
      return page(values);
    }
    if (resource.endsWith("/applications") && method === "POST") {
      if (state.applications.some(item => item.job_id === data.job_id && item.candidate_id === data.candidate_id))
        return error("APPLICATION_ALREADY_EXISTS");
      const item = { id: ids.application, organization_id: ids.org, ...data, status: "applied", updated_at: date };
      state.applications.push(item); return json(item, 201);
    }
    if (resource.endsWith("/transitions")) {
      const item = state.applications.find(value => resource.includes(value.id));
      if (!nextStatuses[item.status].includes(data.status)) return error("INVALID_APPLICATION_STATUS_TRANSITION");
      item.status = data.status; return json(item);
    }
    if (resource.endsWith("/embedding-jobs") && method === "POST") {
      if (state.semanticDisabled) return error("SEMANTIC_DISABLED", 503);
      state.embedding = { id: ids.embedding, model_tag: "qwen3-embedding:0.6b", chunk_count: 2,
        status: "queued", attempts: data.retry ? 2 : 1 };
      return json(state.embedding, 202);
    }
    if (resource.includes("/embedding-jobs/")) return json(state.embedding);
    if (resource.endsWith(`/documents/${ids.document}`) && method === "DELETE") {
      state.documents = []; return new Response(null, { status: 204 });
    }
    if (resource.endsWith("/documents")) {
      const candidate = resource.split("/candidates/")[1].split("/")[0];
      return json(state.documents.filter(item => item.candidate_id === candidate));
    }
    if (resource.endsWith("/extraction")) return json({ status: method === "POST" ? "queued" : "succeeded" });
    if (resource.endsWith("/chunks")) return json({});
    if (resource.endsWith("/match-profile")) return error("JOB_MATCH_PROFILE_NOT_FOUND", 404);
    if (resource.endsWith("/search-profile")) return error("JOB_SEARCH_PROFILE_NOT_FOUND", 404);
    const candidate = state.candidates.find(item => resource.endsWith(`/candidates/${item.id}`));
    if (candidate) return json(candidate);
    if (resource.endsWith(`/jobs/${ids.job}`)) return json(state.jobs[0]);
    state.unexpected.push(`${method} ${path}`);
    return error("UNEXPECTED_FIXTURE_ROUTE", 500);
  };
  await import(`../../app/web/assets/app.mjs?scenario=${++instance}`);
  elements.get("auth-email").value = "fixture@example.com";
  elements.get("auth-password").value = "synthetic-password";
  elements.get("auth-form").emit("submit");
  await wait(() => elements.get("candidate-list").textContent.includes("Candidate 0")
    && !elements.get("profiles-fields").disabled && !elements.get("job-browser-fields").disabled);
  return {
    state, elements, wait,
    button(root, text) { return visit(elements.get(root)).find(item => item.tag === "button" && item.textContent === text); },
    async selectCandidate() {
      visit(elements.get("candidate-list")).find(item => item.tag === "button").click();
      await wait(() => elements.get("documents-list").textContent.includes("synthetic.pdf"));
    },
    async close() { await dom.restore(); assert.deepEqual(state.unexpected, []); },
  };
}
