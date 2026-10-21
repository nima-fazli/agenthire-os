import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { apiClient, syncCards } from "../app/web/assets/agent-ui.mjs";

test("a stale unauthorized body cannot expire a replacement agent session", async () => {
  const saved = globalThis.fetch;
  let finish,
    expired = 0;
  globalThis.fetch = async () => ({
    ok: false,
    status: 401,
    json: () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  });
  try {
    const api = apiClient(() => expired++);
    api.setToken("old-synthetic-token");
    const read = api("/portal/api/applications");
    while (!finish) await new Promise((resolve) => setTimeout(resolve, 0));
    const rejected = assert.rejects(read, { name: "AbortError" });
    api.setToken("replacement-synthetic-token");
    finish({ error: { code: "INVALID_ACCESS_TOKEN" } });
    await rejected;
    assert.equal(expired, 0);
  } finally {
    globalThis.fetch = saved;
  }
});

test("a stalled body ends with useful timeout feedback even if transport ignores abort", async () => {
  const saved = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    json: () => new Promise(() => {}),
  });
  try {
    const api = apiClient(
      () => assert.fail("A timeout must not expire the account"),
      10,
    );
    await assert.rejects(api("/portal/api/applications"), /request timed out/);
  } finally {
    globalThis.fetch = saved;
  }
});

test("agent requests use a private bounded transport and refuse foreign paths", async () => {
  const saved = globalThis.fetch;
  let options;
  globalThis.fetch = async (_path, value) => {
    options = value;
    return { ok: true, status: 200, json: async () => ({ ok: true }) };
  };
  try {
    const api = apiClient(() => {});
    api.setToken("synthetic-token");
    await api("/portal/api/applications");
    assert.equal(options.headers.Authorization, "Bearer synthetic-token");
    assert.equal(options.credentials, "omit");
    assert.equal(options.redirect, "error");
    assert.equal(options.cache, "no-store");
    await assert.rejects(api("//foreign.example/path"), /Invalid API path/);
  } finally {
    globalThis.fetch = saved;
  }
});

test("unchanged polling keeps the same actionable card and unsent draft", () => {
  const container = {
    children: [],
    querySelector: () => null,
    append(node) {
      this.children.push(node);
    },
    replaceChildren() {
      this.children = [];
    },
  };
  let rendered = 0;
  const render = () => ({
    dataset: {},
    draft: "unsent answer",
    remove() {},
    replaceWith() {
      assert.fail("Unchanged cards must not be replaced");
    },
  });
  const items = [{ id: "synthetic-one", status: "pending" }];
  syncCards(container, items, (item) => {
    rendered++;
    return render(item);
  });
  const card = container.children[0];
  syncCards(container, items, () => assert.fail("Should retain existing form"));
  assert.equal(container.children[0], card);
  assert.equal(card.draft, "unsent answer");
  assert.equal(rendered, 1);
});

test("the actual Agent Center controller renders submissions and runs after sign-in", async () => {
  // Match the browser contract: append() returns undefined, never the parent.
  class Element {
    constructor(tag) {
      this.tag = tag;
      this.children = [];
      this.dataset = {};
      this.listeners = new Map();
      this.className = "";
      this.value = "";
      this.textContent = "";
      this.hidden = false;
      this.isConnected = true;
      this.classList = {
        toggle: (name, enabled) => {
          const names = new Set(this.className.split(/\s+/).filter(Boolean));
          enabled ? names.add(name) : names.delete(name);
          this.className = [...names].join(" ");
        },
      };
    }
    append(...nodes) {
      for (const node of nodes) {
        node.parent = this;
        this.children.push(node);
        if (this.tag === "select" && !this.value) this.value = node.value;
      }
    }
    replaceChildren(...nodes) {
      this.children = [];
      this.append(...nodes);
    }
    remove() {
      this.parent.children = this.parent.children.filter((n) => n !== this);
    }
    replaceWith(node) {
      node.parent = this.parent;
      this.parent.children.splice(this.parent.children.indexOf(this), 1, node);
    }
    querySelector(selector) {
      return (
        this.children.find((node) =>
          node.className.split(" ").includes(selector.slice(1)),
        ) || null
      );
    }
    setAttribute(name, value) {
      this[name] = value;
    }
    addEventListener(name, callback) {
      if (!this.listeners.has(name)) this.listeners.set(name, []);
      this.listeners.get(name).push(callback);
    }
    dispatch(name) {
      for (const callback of this.listeners.get(name) || [])
        callback({ preventDefault() {} });
    }
    scrollIntoView() {}
    focus() {}
  }
  const saved = Object.fromEntries(
    ["document", "window", "fetch", "setInterval", "clearInterval"].map(
      (key) => [key, globalThis[key]],
    ),
  );
  const html = await readFile(
    new URL("../app/web/assets/agent-center.html", import.meta.url),
    "utf8",
  );
  const recording = JSON.parse(
    await readFile(
      new URL("../app/web/assets/demo-run.json", import.meta.url),
      "utf8",
    ),
  );
  const nodes = new Map(
    [...html.matchAll(/<([a-z]+)\b[^>]*\bid="([^"]+)"/g)].map((match) => [
      match[2],
      new Element(match[1]),
    ]),
  );
  const names = ["Alex Morgan", "Maya Chen", "Sam Rivera"];
  const submissions = names.map((full_name, index) => ({
    id: `submission-${index}`,
    full_name,
    job_title: "Backend Engineer",
    status: "Received",
  }));
  const runs = submissions.map((s, index) => ({
    id: `run-${index}`,
    submission_id: s.id,
    kind: "recruiter",
    mode: "replay",
    status: "waiting_approval",
    model: "replay",
    steps: 5,
  }));
  const responses = {
    "/auth/login": { access_token: "synthetic-test-token" },
    "/auth/logout": {},
    "/organizations": [{ id: "synthetic-org", name: "AgentHire Demo Lab" }],
    "/organizations/synthetic-org/access": { can_write: true, role: "owner" },
    "/organizations/synthetic-org/jobs": [
      { id: "synthetic-job", title: "Backend Engineer" },
    ],
    "/organizations/synthetic-org/applicant-submissions": submissions,
    "/organizations/synthetic-org/agent-runs": runs,
    "/organizations/synthetic-org/agent-notifications": [],
    "/organizations/synthetic-org/agent-mail-status": [],
    "/organizations/synthetic-org/career-publications/synthetic-job": {
      public_description: "Fictional public Python backend role.",
      published: true,
    },
    "/organizations/synthetic-org/agent-runs/run-0": {
      ...runs[0],
      goal: "Review the saved criteria.",
      input_tokens: 0,
      output_tokens: 0,
      elapsed_ms: 0,
      model_digest: null,
      report: recording.report,
      events: [],
      source_fingerprint: "synthetic-fingerprint",
    },
  };
  const all = (node) => [node, ...node.children.flatMap(all)];
  const settle = async (condition) => {
    for (let i = 0; i < 40 && !condition(); i++)
      await new Promise((resolve) => setImmediate(resolve));
    assert.ok(
      condition(),
      nodes.get("agent-message").textContent || "Controller did not render",
    );
    assert.ok(
      !nodes.get("agent-message").className.includes("is-error"),
      nodes.get("agent-message").textContent,
    );
  };
  try {
    globalThis.document = {
      getElementById: (id) => {
        assert.ok(nodes.has(id), `Missing element in actual HTML: ${id}`);
        return nodes.get(id);
      },
      createElement: (tag) => new Element(tag),
    };
    globalThis.window = { addEventListener() {} };
    globalThis.setInterval = () => 1;
    globalThis.clearInterval = () => {};
    globalThis.fetch = async (path) => {
      assert.ok(
        Object.hasOwn(responses, path),
        `Unexpected API request: ${path}`,
      );
      return {
        ok: true,
        status: 200,
        json: async () => structuredClone(responses[path]),
      };
    };
    await import(
      `../app/web/assets/agent-center.mjs?render-test=${Date.now()}`
    );
    nodes.get("agent-email").value = "owner@example.test";
    nodes.get("agent-password").value = "synthetic-test-only";
    nodes.get("agent-auth-form").dispatch("submit");
    await settle(() => nodes.get("agent-runs").children.length === 3);
    assert.equal(nodes.get("agent-submissions").children.length, 3);
    for (let i = 0; i < 3; i++) {
      const card = nodes.get("agent-submissions").children[i];
      assert.ok(all(card).some((node) => node.textContent === names[i]));
      assert.ok(
        all(card).some(
          (node) =>
            node.tag === "button" && node.textContent === "Start review",
        ),
      );
    }
    all(nodes.get("agent-runs").children[0])
      .find((node) => node.textContent === "Inspect run")
      .dispatch("click");
    await settle(() =>
      all(nodes.get("agent-run-detail")).some(
        (node) => node.textContent === recording.report.summary,
      ),
    );
    assert.ok(
      all(nodes.get("agent-run-detail")).some(
        (node) => node.textContent === recording.report.question,
      ),
    );
    nodes.get("agent-logout").dispatch("click");
    await settle(() => nodes.get("agent-private").hidden);
    assert.equal(nodes.get("agent-submissions").children.length, 0);
    assert.equal(nodes.get("agent-runs").children.length, 0);
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
});
