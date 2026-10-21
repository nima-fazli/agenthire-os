import test from "node:test";
import assert from "node:assert/strict";
import { createNotifications } from "../app/web/assets/notifications.mjs";
import { Element, installDOM, pageResponse } from "./helpers/recruiter_dom.mjs";

function fixture() {
  const fields = Object.fromEntries(
    ["region", "status", "alert", "dismiss"].map(
      key => [key, new Element()],
    ),
  );

  fields.region.append(fields.status, fields.dismiss);

  let next = 0;
  const timers = new Map();

  const clock = {
    setTimeout(fn) {
      timers.set(++next, fn);
      return next;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
  };

  return {
    fields,
    timers,
    feedback: createNotifications(fields, clock),
  };
}

function historyFixture() {
  class HistoryElement extends Element {
    constructor() { super(); this.attributes = {}; }
    setAttribute(name, value) { this.attributes[name] = value; }
  }
  const fields = Object.fromEntries(["region", "status", "alert", "dismiss", "title", "symbol",
    "history", "count", "toggle", "markRead", "clearHistoryButton"].map(key => [key, new HistoryElement()]));
  fields.history.ownerDocument = { createElement: () => new HistoryElement() };
  const clock = { setTimeout: () => 1, clearTimeout() {} };
  return { fields, feedback: createNotifications(fields, clock) };
}

test("notification history bounds memory, keeps text inert, and marks actual unread entries", () => {
  const { fields, feedback } = historyFixture();
  for (let i = 0; i < 24; i++) feedback.show(`Saved ${i}`);
  assert.equal(fields.history.children.length, 20);
  assert.equal(fields.count.textContent, "20");
  assert.doesNotMatch(fields.history.textContent, /Saved 0Workspace/);
  feedback.show("<img src=x onerror=alert(1)>", true);
  assert.match(fields.history.textContent, /<img src=x onerror=alert\(1\)>/);
  fields.markRead.emit("click");
  assert.equal(fields.count.hidden, true);
  assert.equal(fields.markRead.disabled, true);
  assert.ok(fields.history.children.every(item => item.className.includes("is-read")));
  feedback.show("A new update");
  assert.equal(fields.count.textContent, "1");
});

test("resetting workspace history removes prior private text and active feedback", () => {
  const { fields, feedback } = historyFixture();
  feedback.show("PRIVATE ORGANIZATION / CANDIDATE", true);
  feedback.resetHistory();
  assert.doesNotMatch(fields.history.textContent, /PRIVATE/);
  assert.equal(fields.status.textContent, "");
  assert.equal(fields.alert.textContent, "");
  assert.equal(fields.region.hidden, true);
  assert.equal(fields.count.hidden, true);
  assert.equal(fields.clearHistoryButton.disabled, true);
  feedback.show("New organization saved");
  fields.clearHistoryButton.emit("click");
  assert.doesNotMatch(fields.history.textContent, /New organization/);
});

test("success popup is dismissible and clears its timer", () => {
  const { fields, timers, feedback } = fixture();

  feedback.show("Saved");
  assert.equal(fields.region.hidden, false);
  assert.equal(timers.size, 1);

  fields.dismiss.emit("click");
  assert.equal(fields.region.hidden, true);
  assert.equal(timers.size, 0);
});

test("errors persist and are announced once in the assertive region", () => {
  const { fields, timers, feedback } = fixture();

  feedback.show("Safe error", true);

  assert.equal(timers.size, 0);
  assert.equal(fields.status.ariaLive, "off");
  assert.equal(fields.alert.textContent, "Safe error");
});

test("hover pauses expiry and leaving resumes it", () => {
  const { fields, timers, feedback } = fixture();

  feedback.show("Saved");

  fields.region.emit("pointerenter");
  assert.equal(timers.size, 0);

  fields.region.emit("focusin");
  fields.region.emit("pointerleave");
  assert.equal(timers.size, 0);

  fields.region.emit("focusout");
  assert.equal(timers.size, 1);

  [...timers.values()][0]();
  assert.equal(fields.region.hidden, true);
});

test("keyboard focus pauses expiry", () => {
  const { fields, timers, feedback } = fixture();

  feedback.show("Saved");

  fields.region.emit("focusin");
  assert.equal(timers.size, 0);

  fields.region.emit("focusout");
  assert.equal(timers.size, 1);
});

test("empty feedback clears prior text and source-like strings stay plain text", () => {
  const { fields, timers, feedback } = fixture();

  feedback.show("<script>private</script>");
  fields.region.emit("pointerenter");

  assert.equal(fields.status.children.length, 0);

  feedback.show("");

  assert.equal(fields.status.textContent, "");
  assert.equal(fields.region.hidden, true);

  feedback.show("Next saved");
  assert.equal(timers.size, 1);

  feedback.clear();
});

test("a new error cannot be expired by the previous success timer", () => {
  const { fields, timers, feedback } = fixture();

  feedback.show("Saved");
  feedback.show("Safe error", true);

  assert.equal(timers.size, 0);
  assert.equal(fields.region.hidden, false);
});

test("actual controllers show feedback after registration and record creation", async () => {
  const dom = installDOM(), { elements } = dom;
  const org = "11111111-1111-4111-8111-111111111111";
  const other = "22222222-2222-4222-8222-222222222222";
  const jobId = "33333333-3333-4333-8333-333333333333";
  const candidateId = "44444444-4444-4444-8444-444444444444";

  const organizations = [{ id: org, name: "Synthetic" }];
  const jobs = [];
  const candidates = [];
  const documents = [];

  const json = (data, status = 200) => new Response(
    JSON.stringify(data),
    {
      status,
      headers: { "Content-Type": "application/json" },
    },
  );

  globalThis.fetch = async (path, options) => {
    const data = options.body && typeof options.body === "string"
      ? JSON.parse(options.body)
      : null;

    if (path === "/users/register") {
      return json({ id: org, email: data.email }, 201);
    }

    if (path === "/auth/login") {
      return json({ access_token: "a.b.c", session_id: "99999999-9999-4999-8999-999999999999", expires_at: new Date(Date.now() + 1800000).toISOString() });
    }

    if (path === "/auth/logout") return new Response(null, { status: 204 });
    if (path.includes("/access?")) return json({
      organization_id: path.split("/")[2], role: "owner", can_write: true, can_manage: true,
      members: [], invitations: [], events: [], offset: 0, has_more: false,
    });
    if (path === "/users/me") {
      return json({ id: org, email: "fixture@example.com" });
    }

    if (path === "/organizations" && options.method === "POST") {
      const item = { id: other, ...data };
      organizations.push(item);
      return json(item, 201);
    }

    if (path.startsWith("/organizations/page?")) return pageResponse(organizations, path);
    if (path.includes("/recruiting/jobs?")) return pageResponse(jobs, path);
    if (path.includes("/recruiting/candidates?")) return pageResponse(candidates, path);
    if (path.includes("/recruiting/applications?")) return pageResponse([], path);

    if (path.endsWith("/jobs") && options.method === "POST") {
      const item = {
        id: jobId,
        organization_id: other,
        ...data,
      };

      jobs.push(item);
      return json(item, 201);
    }

    if (path.endsWith("/jobs")) return json(jobs);

    if (path.endsWith("/candidates") && options.method === "POST") {
      const item = {
        id: candidateId,
        organization_id: other,
        ...data,
      };

      candidates.push(item);
      return json(item, 201);
    }

    if (path.endsWith("/candidates")) return json(candidates);

    if (path.endsWith("/match-profile")) {
      return json(
        { error: { code: "JOB_MATCH_PROFILE_NOT_FOUND" } },
        404,
      );
    }

    if (path.endsWith("/search-profile")) {
      return json(
        { error: { code: "JOB_SEARCH_PROFILE_NOT_FOUND" } },
        404,
      );
    }

    if (path.includes("/documents?") && options.method === "POST") {
      assert.ok(options.body instanceof Blob);

      const item = {
        id: jobId,
        candidate_id: candidateId,
        organization_id: other,
        filename: "synthetic.pdf",
        size_bytes: 10,
      };

      documents.push(item);
      return json(item, 201);
    }

    if (path.includes("/documents?")) return json(documents);

    throw new Error("Unexpected synthetic route");
  };

  const wait = dom.wait;

  try {
    await import("../app/web/assets/app.mjs");

    elements.get("auth-mode").emit("click");
    elements.get("auth-email").value = "fixture@example.com";
    elements.get("auth-password").value = "synthetic-password";

    elements.get("auth-form").emit("submit");

    await wait(
      () => elements.get("notice").textContent ===
        "Account created. Sign in with your password.",
    );

    assert.equal(elements.get("notification").hidden, false);

    elements.get("auth-password").value = "synthetic-password";
    elements.get("auth-form").emit("submit");

    await wait(() => !elements.get("shell").hidden);

    elements.get("organization-name").value = "Created";
    elements.get("organization-slug").value = "created";
    elements.get("organization-form").emit("submit");

    await wait(
      () => elements.get("notice").textContent === "Organization created.",
    );

    elements.get("job-title").value = "Backend";
    elements.get("job-description").value = "Synthetic";
    elements.get("job-form").emit("submit");

    await wait(
      () => elements.get("notice").textContent === "Job created.",
    );

    elements.get("candidate-name").value = "Synthetic Candidate";
    elements.get("candidate-form").emit("submit");

    await wait(
      () => elements.get("notice").textContent === "Candidate created.",
    );

    elements.get("document-file").files = [
      new File(
        ["%PDF-1.4"],
        "synthetic.pdf",
        { type: "application/pdf" },
      ),
    ];

    elements.get("document-form").emit("submit");

    await wait(
      () => elements.get("notice").textContent === "Resume uploaded.",
    );

    elements.get("logout").emit("click");
    assert.equal(elements.get("shell").hidden, true);

    elements.get("notice-dismiss").emit("click");
  } finally {
    await dom.restore();
  }
});
