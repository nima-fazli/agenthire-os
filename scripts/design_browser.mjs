// Real Chromium checks on the actual workspace with an explicitly synthetic transport.
import { readFile, writeFile, mkdtemp, mkdir, rm, access } from "node:fs/promises";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import assert from "node:assert/strict";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const hash = value => createHash("sha256").update(value).digest("hex");
const canonical = data => data.toString("utf8").replace(/^\uFEFF/, "").replaceAll("\r\n", "\n");
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

export function activateControl(selector, doc = document) {
  const control = doc.querySelector(selector);
  if (!control || control.matches(":disabled") || !control.getClientRects().length) return false;
  control.focus();
  control.click();
  return true;
}

export async function pressKey(call, key) {
  const keys = {
    Enter: { code: "Enter", windowsVirtualKeyCode: 13, text: "\r" },
    Tab: { code: "Tab", windowsVirtualKeyCode: 9, text: "" },
    Escape: { code: "Escape", windowsVirtualKeyCode: 27, text: "" },
  };
  if (!Object.hasOwn(keys, key)) throw new Error("Unsupported browser test key");
  const { text, ...definition } = keys[key];
  const event = { ...definition, key, modifiers: 0 };
  await call("Input.dispatchKeyEvent", {
    ...event, type: text ? "keyDown" : "rawKeyDown", text, unmodifiedText: text,
  });
  await call("Input.dispatchKeyEvent", { ...event, type: "keyUp" });
}

function syntheticTransport() {
  const id = n => `${String(n).padStart(8, "0")}-1111-4111-8111-111111111111`;
  const org = id(1), other = id(2), job = id(3), session = id(4);
  const date = "2026-10-20T00:00:00Z";
  const jobs = [{ id: job, organization_id: org, title: "Senior Backend Engineer", status: "open",
    description: "Build reliable APIs and data systems. Review Python, PostgreSQL, and distributed processing experience.", updated_at: date }];
  const names = ["Alex Morgan", "Sam Rivera", "Jordan Lee", "Casey Patel", "Taylor Chen", "Robin Ellis"];
  const portraits = ["alex", "daniel", "priya", "maria", "james", "fatima"];
  const locations = ["San Francisco, CA", "Austin, TX", "Seattle, WA", "New York, NY", "Boston, MA", "Chicago, IL"];
  const candidates = names.map((full_name, i) => ({ id: id(i + 10), organization_id: org, full_name,
    headline: i % 2 ? "Software Engineer · Python & PostgreSQL" : "Backend Engineer · APIs & distributed systems",
    email: `sample${i}@example.com`, location: locations[i], synthetic_portrait: portraits[i],
    summary: "Software engineer focused on reliable services, thoughtful collaboration, and maintainable systems. This is a synthetic record for exploring the workspace.",
    phone: null, updated_at: date }));
  const applications = [{ id: id(70), organization_id: org, job_id: job, candidate_id: candidates[0].id,
    candidate_name: candidates[0].full_name, job_title: jobs[0].title, status: "screening",
    synthetic_portrait: "alex",
    allowed_statuses: ["interview", "rejected"], updated_at: date }];
  const response = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
  const error = (code, status) => response({ error: { code, message: "SYNTHETIC_PRIVATE_MESSAGE" } }, status);
  const page = (items, url) => {
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    let filtered = q ? items.filter(item => [item.name, item.title, item.full_name, item.candidate_name, item.job_title]
      .some(value => typeof value === "string" && value.toLowerCase().includes(q))) : items;
    if (url.searchParams.get("status")) filtered = filtered.filter(item => item.status === url.searchParams.get("status"));
    const offset = Number(url.searchParams.get("offset") ?? 0), limit = Number(url.searchParams.get("limit") ?? 20);
    return response({ items: filtered.slice(offset, offset + limit), total: filtered.length, offset, limit });
  };
  window.fetch = async (path, options = {}) => {
    const url = new URL(path, "http://synthetic.invalid"), resource = url.pathname;
    if (resource === "/auth/login") return response({ access_token: "synthetic.session.only", session_id: session,
      expires_at: new Date(Date.now() + 1800000).toISOString() });
    if (resource === "/auth/logout") return new Response(null, { status: 204 });
    if (options.headers?.Authorization !== "Bearer synthetic.session.only") return error("INVALID_ACCESS_TOKEN", 401);
    if (resource.endsWith("/transitions") && options.method === "POST") {
      const application = applications.find(item => resource.endsWith(`/applications/${item.id}/transitions`));
      const target = JSON.parse(options.body).status;
      if (!application || !application.allowed_statuses.includes(target)) return error("INVALID_APPLICATION_TRANSITION", 409);
      const next = { applied: ["screening", "rejected"], screening: ["interview", "rejected"],
        interview: ["offer", "rejected"], offer: ["hired", "rejected"], hired: [], rejected: [] };
      application.status = target;
      application.allowed_statuses = next[target];
      return response(application);
    }
    if (resource === "/users/me") return response({ id: id(50), email: "reviewer@example.com" });
    if (resource === "/auth/sessions") return response([{ id: session, current: true, created_at: date, expires_at: new Date(Date.now() + 1800000).toISOString() }]);
    if (resource === "/organizations/page") return page([{ id: org, name: "Northstar Studio" }, { id: other, name: "Empty workspace" }], url);
    if (resource.endsWith("/access")) return response({ organization_id: resource.split("/")[2], role: "owner", can_write: true,
      can_manage: true, members: [], invitations: [], events: [], offset: 0, has_more: false });
    if (resource.includes("/recruiting/")) {
      if (resource.endsWith("/jobs")) return page(resource.includes(other) ? [] : jobs, url);
      if (resource.endsWith("/candidates")) {
        if (url.searchParams.get("q") === "simulate-error") return error("HTTP_ERROR", 503);
        if (url.searchParams.get("q") === "simulate-delay") await new Promise(resolve => setTimeout(resolve, 1500));
        return page(resource.includes(other) ? [] : candidates, url);
      }
      if (resource.endsWith("/applications")) return page(resource.includes(other) ? [] : applications, url);
    }
    if (resource.endsWith("/match-profile")) return error("JOB_MATCH_PROFILE_NOT_FOUND", 404);
    if (resource.endsWith("/search-profile")) return error("JOB_SEARCH_PROFILE_NOT_FOUND", 404);
    if (resource.endsWith("/documents")) return response([]);
    const candidate = candidates.find(item => resource.endsWith(`/candidates/${item.id}`));
    if (candidate) return response(candidate);
    if (resource.endsWith(`/jobs/${job}`)) return response(jobs[0]);
    return error("FIXTURE_ROUTE_NOT_IMPLEMENTED", 501);
  };
  const banner = document.createElement("aside");
  banner.className = "qa-banner";
  const text = document.createElement("p");
  text.textContent = "Design fixture · Synthetic records · No network or project database";
  const open = document.createElement("button");
  open.id = "qa-open"; open.type = "button"; open.className = "button secondary";
  open.textContent = "Open synthetic workspace";
  open.addEventListener("click", () => {
    document.getElementById("auth-email").value = "reviewer@example.com";
    document.getElementById("auth-password").value = "synthetic-design-password";
    document.getElementById("auth-form").requestSubmit();
  });
  banner.append(text, open); document.body.append(banner);
}

export async function buildPreview(assets = join(root, "app/web/assets")) {
  const modules = new Map(), visiting = new Set();
  const embedded = new Map();
  async function embed(source) {
    for (const match of source.matchAll(/\/workspace\/assets\/([\w-]+\.(?:svg|webp|woff2))/g)) {
      const name = match[1];
      if (!embedded.has(name)) {
        const mime = name.endsWith(".svg") ? "image/svg+xml" : name.endsWith(".webp") ? "image/webp" : "font/woff2";
        let raw = await readFile(join(assets, name));
        if (name.endsWith(".svg")) raw = Buffer.from(canonical(raw));
        embedded.set(name, `data:${mime};base64,${raw.toString("base64")}`);
      }
      source = source.replaceAll(match[0], embedded.get(name));
    }
    return source;
  }
  async function bundle(name) {
    if (modules.has(name)) return;
    if (visiting.has(name)) throw new Error("Cyclic browser module graph");
    visiting.add(name);
    let source = await embed(canonical(await readFile(join(assets, name))));
    const imports = [...source.matchAll(/import\s*\{([^}]+)\}\s*from\s*"\.\/([^"]+)";/g)];
    for (const [, , dependency] of imports) await bundle(dependency);
    source = source.replace(/import\s*\{([^}]+)\}\s*from\s*"\.\/([^"]+)";/g,
      (_match, names, dependency) => `const {${names}} = modules[${JSON.stringify(dependency)}];`);
    const exports = [...source.matchAll(/^export[ \t]+(?:async[ \t]+)?(?:function|class|const|let)[ \t]+([A-Za-z_$][\w$]*)/gm)].map(match => match[1]);
    modules.set(name, `modules[${JSON.stringify(name)}] = (() => {\n${source.replaceAll(/^export[ \t]+/gm, "")}\nreturn {${exports.join(",")}};\n})();`);
    visiting.delete(name);
  }
  await bundle("app.mjs"); await bundle("design.mjs");
  const script = `(${syntheticTransport.toString()})();\nconst modules = Object.create(null);\n${[...modules.values()].join("\n")}`.replaceAll("\r\n", "\n");
  assert(!script.includes("</script"), "Unsafe embedded script terminator");
  const style = await embed(canonical(await readFile(join(assets, "styles.css"))));
  let html = await embed(canonical(await readFile(join(assets, "index.html"))));
  html = html.replace(/\s*<script[^>]*>[^<]*<\/script>/g, "").replace(/\s*<link rel="stylesheet"[^>]*>/g, "");
  const csp = `default-src 'none'; script-src 'sha256-${createHash("sha256").update(script).digest("base64")}'; style-src 'sha256-${createHash("sha256").update(style).digest("base64")}'; connect-src 'none'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'`;
  return html.replace("<head>", `<head>\n<meta http-equiv="Content-Security-Policy" content="${csp}">`)
    .replace("</head>", `<style>${style}</style></head>`).replace("</body>", `<script type="module">${script}</script></body>`);
}

async function sourceDigest() {
  const manifest = JSON.parse(canonical(await readFile(join(root, "scripts/fixtures/design_stage5_manifest.json"))));
  const content = {};
  for (const name of [...manifest.feature_files, ...manifest.test_files].sort()) content[name] = hash(canonical(await readFile(join(root, name))));
  return hash(JSON.stringify(content));
}

async function browserPath(explicit) {
  const candidates = [explicit, process.env.AGENTHIRE_BROWSER_BINARY,
    ...[process.env.ProgramFiles, process.env["ProgramFiles(x86)"], process.env.LOCALAPPDATA].filter(Boolean)
      .flatMap(base => [join(base, "Microsoft/Edge/Application/msedge.exe"), join(base, "Google/Chrome/Application/chrome.exe")]),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"];
  for (const path of candidates.filter(Boolean)) { try { await access(path); return path; } catch {} }
  throw new Error("Chrome or Edge not found; set AGENTHIRE_BROWSER_BINARY to an installed Chromium browser.");
}

class CDP {
  constructor(socket) {
    this.socket = socket; this.sequence = 0; this.pending = new Map(); this.errors = [];
    socket.addEventListener("message", event => {
      const message = JSON.parse(event.data);
      if (message.method === "Runtime.exceptionThrown") this.errors.push("uncaught_browser_exception");
      const task = this.pending.get(message.id);
      if (task) { clearTimeout(task.timer); this.pending.delete(message.id); message.error ? task.reject(new Error(message.error.message)) : task.resolve(message.result); }
    });
    socket.addEventListener("close", () => {
      for (const task of this.pending.values()) { clearTimeout(task.timer); task.reject(new Error("Browser connection closed")); }
      this.pending.clear();
    });
  }
  call(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      const id = ++this.sequence;
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`Browser command timeout: ${method}`)); }, 15000);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }
  async evaluate(expression, sessionId, checkpoint) {
    const result = await this.call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }, sessionId);
    if (result.exceptionDetails) throw new Error(`Browser evaluation failed: ${checkpoint}`);
    return result.result.value;
  }
}

async function run(options) {
  const directory = await mkdtemp(join(tmpdir(), "agenthire-design-"));
  let child, connection, interrupted = false;
  const report = { version: "design-browser-v1", source_kind: "browser_synthetic_fixture", source_sha256: await sourceDigest(),
    status: "failed", cleanup: "pending", browser: "Chromium", checks: [], diagnostic: null };
  const interrupt = () => {
    interrupted = true;
    connection?.socket.close();
    if (child && child.exitCode === null) child.kill();
  };
  process.on("SIGINT", interrupt); process.on("SIGTERM", interrupt);
  try {
    const file = join(directory, "workspace.html"); await writeFile(file, await buildPreview());
    const binary = await browserPath(options.browser);
    if (interrupted) throw new Error("Browser check interrupted");
    child = spawn(binary, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
      "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", `--user-data-dir=${join(directory, "profile")}`, "about:blank"], { stdio: "ignore" });
    let launchError = false; child.on("error", () => { launchError = true; });
    let endpoint;
    for (let i = 0; i < 150; i++) {
      if (launchError || child.exitCode !== null) throw new Error("Isolated browser did not start");
      try { const [port, path] = (await readFile(join(directory, "profile/DevToolsActivePort"), "utf8")).trim().split("\n"); endpoint = `ws://127.0.0.1:${Number(port)}${path}`; break; } catch { await delay(100); }
    }
    if (!endpoint) throw new Error("Isolated browser startup timed out");
    const socket = new WebSocket(endpoint);
    await new Promise((yes, no) => {
      const timer = setTimeout(() => { socket.close(); no(new Error("Browser connection timed out")); }, 15000);
      socket.addEventListener("open", () => { clearTimeout(timer); yes(); }, { once: true });
      socket.addEventListener("error", () => { clearTimeout(timer); no(new Error("Browser connection failed")); }, { once: true });
    });
    connection = new CDP(socket);
    const version = await connection.call("Browser.getVersion"); report.browser = version.product;
    const target = await connection.call("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await connection.call("Target.attachToTarget", { targetId: target.targetId, flatten: true });
    const call = (method, params) => connection.call(method, params, sessionId);
    const evaluate = (expression, checkpoint) => connection.evaluate(expression, sessionId, checkpoint);
    await call("Page.enable"); await call("Runtime.enable"); await call("Page.bringToFront");
    const wait = async (checkpoint, expression) => {
      for (let i = 0; i < 100; i++) {
        if (connection.errors.length) throw new Error(`Uncaught browser exception: ${checkpoint}`);
        if (await evaluate(expression, checkpoint)) return;
        await delay(50);
      }
      throw new Error(`Browser state deadline exceeded: ${checkpoint}`);
    };
    const click = async selector => {
      const target = `document.querySelector(${JSON.stringify(selector)})`;
      await wait(`control-ready:${selector}`, `(() => { const control=${target}; return Boolean(control && !control.matches(':disabled') && control.getClientRects().length); })()`);
      assert.equal(await evaluate(`(${activateControl.toString()})(${JSON.stringify(selector)})`, `activate:${selector}`), true, `Control activation failed: ${selector}`);
    };
    const check = async (name, expression) => { assert.equal(await evaluate(expression, name), true, name); report.checks.push({ name, passed: true }); };
    await call("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
    await call("Page.navigate", { url: pathToFileURL(file).href });
    await wait("fixture-bootstrap", "Boolean(document.getElementById('qa-open'))");
    await check("public-sign-in-and-labels", "!document.getElementById('auth-view').hidden && document.documentElement.lang==='en' && document.querySelectorAll('main').length===1");
    await click("#qa-open"); await wait("synthetic-sign-in", "document.querySelectorAll('.candidate-card').length===6 && !document.getElementById('retrieval-run').disabled");
    await check("signed-in-context", "document.getElementById('selection-context').textContent.includes('Senior Backend Engineer')");
    for (const view of ["setup", "applications", "access", "account", "review"]) {
      await click(`[data-workspace-view="${view}"]`);
      await check(`navigation-${view}`, `document.querySelectorAll('[data-view-panel]:not([hidden])').length===1 && document.querySelector('[aria-current="page"]').dataset.workspaceView===${JSON.stringify(view)} && document.activeElement.matches('[tabindex="-1"]')`);
    }
    await click('[data-workspace-view="applications"]');
    await wait("application-list", "document.querySelectorAll('.application-card').length===1");
    await click(".application-card button");
    await wait("application-candidate-focus", "document.activeElement.id==='candidate-panel'");
    await check("application-candidate-navigation", "document.querySelector('[aria-current=page]').dataset.workspaceView==='applications'");
    await click('[data-workspace-view="review"]');
    await click('[data-workspace-view="applications"]');
    await evaluate("const select=document.querySelector('.application-card select');select.value='interview';select.dispatchEvent(new Event('change'))", "application-status-selection");
    await click(".application-card button:last-child");
    await check("confirmation-cancel-focus", "document.getElementById('confirm-dialog').open && document.activeElement.id==='confirm-cancel'");
    await pressKey(call, "Escape");
    await wait("confirmation-cancel-return-focus", "!document.getElementById('confirm-dialog').open && document.activeElement.textContent==='Update status'");
    await click('[data-workspace-view="review"]');
    await click(".candidate-card button"); await wait("candidate-dossier", "document.getElementById('candidate-heading').textContent.includes('Alex Morgan')");
    for (const [width, height] of [[1440, 1000], [1024, 900], [768, 1024], [390, 844], [320, 740]]) {
      await call("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
      await check(`layout-${width}`, "document.documentElement.scrollWidth <= innerWidth + 1 && [...document.querySelectorAll('button:not(:disabled),summary')].filter(e=>e.getClientRects().length).every(e=>e.getBoundingClientRect().height>=43)");
    }
    await evaluate("document.getElementById('workspace-help').focus()", "keyboard-guide-focus");
    await wait("keyboard-guide-trigger-focus", "document.activeElement.id==='workspace-help' && !document.getElementById('help-dialog').open");
    await pressKey(call, "Enter");
    await wait("keyboard-guide-open", "document.getElementById('help-dialog').open && document.activeElement.id==='help-close'");
    await check("keyboard-guide-open", "document.getElementById('help-dialog').open && document.activeElement.id==='help-close'");
    await pressKey(call, "Tab");
    await check("modal-focus-contained", "document.getElementById('help-dialog').contains(document.activeElement) || document.activeElement===document.body");
    await pressKey(call, "Escape");
    await wait("keyboard-guide-return-focus", "!document.getElementById('help-dialog').open && document.activeElement.id==='workspace-help'");
    await check("keyboard-guide-close", "!document.getElementById('help-dialog').open && document.activeElement.id==='workspace-help'");
    await evaluate("document.getElementById('candidate-filter').value='no-match';document.getElementById('candidate-search-form').requestSubmit()", "empty-search-submit");
    await wait("empty-search", "document.getElementById('candidate-list').textContent.includes('No candidates')");
    report.checks.push({ name: "empty-search-state", passed: true });
    await evaluate("document.getElementById('candidate-filter').value='simulate-error';document.getElementById('candidate-search-form').requestSubmit()", "error-search-submit");
    await wait("error-notification", "document.getElementById('notice').classList.contains('error')");
    await check("safe-error-notification", "!document.getElementById('notice').textContent.includes('SYNTHETIC_PRIVATE_MESSAGE')");
    await evaluate("document.getElementById('organization-select').value='00000002-1111-4111-8111-111111111111';document.getElementById('organization-select').dispatchEvent(new Event('change'))", "organization-switch-submit");
    await wait("organization-switch", "document.getElementById('organization-heading').textContent==='Empty workspace'");
    await check("context-switch-clears-private-dossier", "!document.getElementById('candidate-heading').textContent.includes('Alex Morgan')");
    await click("#account-toggle");
    await click("#logout");
    await check("sign-out-clears-private-shell", "document.getElementById('shell').hidden && !document.getElementById('account-email').textContent && !document.getElementById('auth-password').value");
    assert.deepEqual(connection.errors, [], "Uncaught browser exceptions");
    report.checks.push({ name: "no-uncaught-browser-exceptions", passed: true }); report.status = "passed";
  } catch (error) { report.diagnostic = interrupted ? "interrupted" : String(error.message).slice(0, 240); }
  finally {
    try {
      if (connection) { await connection.call("Browser.close").catch(() => {}); connection.socket.close(); }
      if (child && child.exitCode === null) child.kill();
      await rm(directory, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 }); report.cleanup = "completed";
    } catch { report.cleanup = "attention_required"; report.status = "failed"; }
  }
  process.removeListener("SIGINT", interrupt); process.removeListener("SIGTERM", interrupt);
  if (interrupted) { report.status = "failed"; report.diagnostic = "interrupted"; }
  if (options.report) { await mkdir(dirname(options.report), { recursive: true }); await writeFile(options.report, JSON.stringify(report, null, 2) + "\n"); }
  console.log(JSON.stringify(report)); return report.status === "passed" && report.cleanup === "completed" ? 0 : 2;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const options = {};
  for (let i = 2; i < process.argv.length; i += 2) {
    const key = process.argv[i].replace(/^--/, "");
    if (!["export", "browser", "report"].includes(key) || !process.argv[i + 1]) throw new Error("Use --export FILE, --report FILE, or --browser BINARY.");
    options[key] = resolve(process.argv[i + 1]);
  }
  if (options.export) { await writeFile(options.export, await buildPreview()); console.log("Synthetic browser fixture exported."); }
  else process.exitCode = await run(options);
}
