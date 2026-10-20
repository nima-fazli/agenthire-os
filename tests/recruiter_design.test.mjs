import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { activateControl, buildPreview, pressKey } from "../scripts/design_browser.mjs";
import { createDesign, viewForTarget } from "../app/web/assets/design.mjs";
import { Element, installDOM, visit } from "./helpers/recruiter_dom.mjs";

function fixture({ mobile = false } = {}) {
  const ids = ["shell", "context-switcher", "help-dialog", "workspace-view-label", "candidates-panel", "candidate-panel",
    "profiles-panel", "applications-panel", "access-panel", "account-panel", "organization-select",
    "job-select", "selection-context", "workspace-start", "context-open", "workspace-help", "help-close",
    "organization-heading", "job-description-view", "candidate-heading", "auth-email"];
  const elements = new Map();
  let doc;
  class Element extends EventTarget {
    constructor(id) { super(); this.id = id; this.hidden = false; this.dataset = {}; this.attributes = {}; this.value = ""; this.textContent = ""; this.isConnected = true; }
    focus() { doc.activeElement = this; }
    setAttribute(key, value) { this.attributes[key] = value; }
    removeAttribute(key) { delete this.attributes[key]; }
    contains(target) { return target?.insideShell === true; }
    closest() { return this.insideShell && elements.get("shell").hidden ? elements.get("shell") : null; }
    querySelector() { return this; }
    showModal() { this.open = true; }
    close() { this.open = false; this.dispatchEvent(new Event("close")); }
  }
  ids.forEach(id => elements.set(id, new Element(id)));
  const views = ["review", "setup", "applications", "access", "account"];
  const links = views.map(view => { const item = new Element(view); item.dataset.workspaceView = view; return item; });
  const panels = views.map(view => { const item = new Element(view); item.dataset.viewPanel = view; return item; });
  elements.get("shell").hidden = true;
  doc = { getElementById: id => elements.get(id), activeElement: null,
    querySelectorAll: selector => selector.includes("view-panel") ? panels : links };
  const media = new EventTarget(); media.matches = mobile;
  const observers = [];
  const host = { matchMedia: () => media, MutationObserver: class { constructor(callback) { observers.push(callback); } observe() {} disconnect() {} } };
  const controller = createDesign(doc, host);
  return { elements, links, panels, controller, doc, media, observers };
}

test("section navigation selects one view, sets the current link and focuses its panel", () => {
  const f = fixture(); f.elements.get("shell").hidden = false; f.controller.refresh();
  f.links[1].dispatchEvent(new Event("click", { cancelable: true }));
  assert.deepEqual(f.panels.map(panel => panel.hidden), [true, false, true, true, true]);
  assert.equal(f.links[1].attributes["aria-current"], "page");
  assert.equal(f.links[0].attributes["aria-current"], undefined);
  assert.equal(f.doc.activeElement.id, "profiles-panel");
  assert.equal(f.controller.show("__proto__"), false);
  assert.equal(f.panels[1].hidden, false);
});

test("sign-out clears job context, resets the view and moves focus out of hidden content", () => {
  const f = fixture(); const shell = f.elements.get("shell"); shell.hidden = false; f.controller.refresh();
  f.elements.get("organization-select").value = "organization";
  const job = f.elements.get("job-select"); job.value = "job"; job.selectedOptions = [{ textContent: "PRIVATE JOB" }];
  f.controller.refresh(); assert.match(f.elements.get("selection-context").textContent, /PRIVATE JOB/);
  f.controller.show("account");
  f.doc.activeElement = { insideShell: true }; shell.hidden = true; f.controller.refresh();
  assert.equal(f.doc.activeElement.id, "auth-email");
  assert.doesNotMatch(f.elements.get("selection-context").textContent, /PRIVATE JOB/);
  assert.equal(f.panels[0].hidden, false);
});

test("mobile context starts collapsed and can be opened without changing records", () => {
  const f = fixture({ mobile: true });
  assert.equal(f.elements.get("context-switcher").open, false);
  f.elements.get("organization-select").value = "same-record";
  f.elements.get("context-open").dispatchEvent(new Event("click"));
  assert.equal(f.elements.get("context-switcher").open, true);
  assert.equal(f.doc.activeElement.id, "organization-select");
  assert.equal(f.elements.get("organization-select").value, "same-record");
});

test("guide restores focus only to a connected visible trigger", () => {
  const f = fixture(); const trigger = f.elements.get("workspace-help"); trigger.focus();
  trigger.dispatchEvent(new Event("click")); assert.equal(f.doc.activeElement.id, "help-close");
  f.elements.get("help-dialog").close(); assert.equal(f.doc.activeElement, trigger);
  trigger.focus(); trigger.dispatchEvent(new Event("click")); trigger.isConnected = false;
  f.elements.get("help-dialog").close(); assert.equal(f.doc.activeElement.id, "help-close");
});

test("browser keyboard dispatch includes Enter text and ordered navigation key events", async () => {
  const events = [];
  const call = async (method, params) => { events.push({ method, params }); };
  for (const [key, code] of [["Enter", 13], ["Tab", 9], ["Escape", 27]]) {
    events.length = 0;
    await pressKey(call, key);
    assert.equal(events.length, 2);
    assert.ok(events.every(event => event.method === "Input.dispatchKeyEvent"));
    const [down, up] = events.map(event => event.params);
    assert.equal(down.type, key === "Enter" ? "keyDown" : "rawKeyDown");
    assert.equal(down.text, key === "Enter" ? "\r" : "");
    assert.equal(down.unmodifiedText, down.text);
    assert.equal(up.type, "keyUp");
    for (const event of [down, up]) {
      assert.equal(event.key, key);
      assert.equal(event.code, key);
      assert.equal(event.windowsVirtualKeyCode, code);
      assert.equal(event.modifiers, 0);
    }
    assert.equal(Object.hasOwn(up, "text"), false);
    assert.equal(Object.hasOwn(up, "unmodifiedText"), false);
  }
  events.length = 0;
  await assert.rejects(() => pressKey(call, "constructor"), /Unsupported browser test key/);
  assert.equal(events.length, 0);
});

test("section target lookup refuses unrecognized and inherited names", () => {
  assert.equal(viewForTarget("candidate-panel"), null);
  assert.equal(viewForTarget("profiles-panel"), "setup");
  assert.equal(viewForTarget("constructor"), null);
});

test("opening an application candidate moves to the dossier after its heading is rendered", () => {
  const f = fixture(); f.elements.get("shell").hidden = false; f.controller.refresh();
  f.controller.show("applications");
  f.elements.get("candidate-heading").querySelector = () => ({ tagName: "H3" });
  f.observers[0]();
  assert.equal(f.panels[0].hidden, false);
  assert.equal(f.doc.activeElement.id, "candidate-panel");
});

test("offline browser fixture binds its executable assets to CSP hashes", async () => {
  const html = await buildPreview();
  const scripts = [...html.matchAll(/<script type="module">([\s\S]*?)<\/script>/g)];
  const styles = [...html.matchAll(/<style>([\s\S]*?)<\/style>/g)];
  assert.equal(scripts.length, 1);
  assert.equal(styles.length, 1);
  for (const [kind, content] of [["script", scripts[0][1]], ["style", styles[0][1]]]) {
    const hash = createHash("sha256").update(content).digest("base64");
    assert.ok(html.includes(`${kind}-src 'sha256-${hash}'`));
  }
  assert.ok(html.includes("connect-src 'none'"));
  assert.doesNotMatch(html, /<script\b[^>]*\bsrc=|<link\b[^>]*\brel="stylesheet"/i);
});

test("browser fixture is identical for UTF-8 BOM and Windows line endings", async () => {
  const assets = await mkdtemp(join(tmpdir(), "agenthire-design-encoding-"));
  try {
    const source = new URL("../app/web/assets/", import.meta.url);
    for (const name of await readdir(source)) {
      const text = await readFile(new URL(name, source), "utf8");
      await writeFile(join(assets, name), "\uFEFF" + text.replace(/^\uFEFF/, "").replaceAll("\r\n", "\n").replaceAll("\n", "\r\n"));
    }
    assert.equal(await buildPreview(assets), await buildPreview());
  } finally { await rm(assets, { recursive: true, force: true }); }
});

test("bundled browser fixture boots, signs in and renders the synthetic workspace", async () => {
  const html = await buildPreview();
  const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1];
  const f = installDOM();
  try {
    // Supply only controller DOM APIs; native Chromium separately verifies layout.
    const views = ["review", "setup", "applications", "access", "account"];
    const links = views.map(view => {
      const link = new Element("a"); link.dataset = { workspaceView: view }; link.attributes = {};
      link.setAttribute = (key, value) => { link.attributes[key] = value; };
      link.removeAttribute = key => { delete link.attributes[key]; };
      return link;
    });
    const panels = views.map(view => {
      const panel = new Element("section"); panel.dataset = { viewPanel: view }; return panel;
    });
    f.document.querySelectorAll = selector => selector === "[data-view-panel]" ? panels : links;
    window.matchMedia = () => Object.assign(new EventTarget(), { matches: false });
    const observers = [];
    window.MutationObserver = class {
      constructor(callback) { this.callback = callback; this.targets = new Set(); observers.push(this); }
      observe(target) { this.targets.add(target); }
      disconnect() { this.targets.clear(); }
    };
    const heading = f.elements.get("candidate-heading");
    heading.querySelector = selector => selector === "h3" ? visit(heading).find(element => element.tagName === "H3") : null;
    const replaceHeading = heading.replaceChildren.bind(heading);
    heading.replaceChildren = (...items) => {
      replaceHeading(...items);
      for (const observer of observers.filter(value => value.targets.has(heading)))
        queueMicrotask(() => observer.callback());
    };
    Object.defineProperty(window, "fetch", { set(value) { globalThis.fetch = value; } });
    for (const id of ["auth-form", "candidate-search-form"])
      f.elements.get(id).requestSubmit = () => f.elements.get(id).emit("submit");
    new Function(`"use strict";\n${script}`)();
    assert.equal(f.elements.get("auth-view").hidden, false);
    const open = visit(f.document.body).find(element => element.id === "qa-open");
    assert.ok(open);
    open.click();
    await f.wait(() => visit(f.elements.get("candidate-list")).filter(element => element.className === "candidate-card").length === 6
      && !f.elements.get("retrieval-run").disabled, "Bundled synthetic sign-in must finish");
    assert.equal(f.elements.get("shell").hidden, false);
    assert.match(f.elements.get("candidate-list").textContent, /Alex Morgan/);
    assert.equal(f.elements.get("organization-heading").textContent, "Northstar Studio");
    const applicationPath = `/organizations/${f.elements.get("organization-select").value}/recruiting/applications`;
    for (const [query, total] of [["", 1], ["Alex", 1], ["Senior Backend", 1], ["no-match", 0]]) {
      const response = await fetch(`${applicationPath}?limit=20&offset=0&q=${encodeURIComponent(query)}`, {
        headers: { Authorization: "Bearer synthetic.session.only" },
      });
      assert.equal(response.status, 200);
      const page = await response.json();
      assert.equal(page.total, total, `Synthetic application search: ${JSON.stringify(query)}`);
      assert.equal(page.items.length, total);
    }
    const applicationCards = () => visit(f.elements.get("application-list")).filter(element => element.className === "application-card");
    await f.wait(() => applicationCards().length === 1, "Synthetic application must render");
    links[2].click();
    const application = applicationCards()[0];
    const candidate = visit(application).find(element => element.tagName === "BUTTON" && element.textContent === "Open candidate");
    const update = visit(application).find(element => element.tagName === "BUTTON" && element.textContent === "Update status");
    assert.ok(candidate);
    assert.ok(update);
    for (const control of [candidate, update]) {
      control.matches = selector => selector === ":disabled" && control.disabled;
      control.getClientRects = () => control.hidden ? [] : [{}];
    }
    const controls = { querySelector: selector => ({ candidate, update })[selector] };
    assert.equal(activateControl("missing", controls), false);
    assert.equal(activateControl("update", controls), false);
    candidate.hidden = true;
    assert.equal(activateControl("candidate", controls), false);
    candidate.hidden = false;
    assert.equal(activateControl("candidate", controls), true);
    await f.wait(() => heading.textContent.includes("Alex Morgan"), "Application candidate must open");
    assert.equal(links[0].attributes["aria-current"], "page");
    assert.equal(f.document.activeElement, f.elements.get("candidate-panel"));
    links[2].click();
    const status = visit(application).find(element => element.tagName === "SELECT");
    status.value = "interview"; status.emit("change");
    assert.equal(update.disabled, false);
    assert.equal(activateControl("update", controls), true);
    const dialog = f.elements.get("confirm-dialog");
    assert.equal(dialog.open, true);
    assert.equal(f.document.activeElement, f.elements.get("confirm-cancel"));
    dialog.emit("cancel");
    assert.equal(dialog.open, false);
    assert.equal(f.document.activeElement, update);
    links[1].click();
    assert.deepEqual(panels.map(panel => panel.hidden), [true, false, true, true, true]);
    assert.equal(links[1].attributes["aria-current"], "page");
    assert.equal(f.document.activeElement, f.elements.get("profiles-panel"));
    links[0].click();
    f.elements.get("candidate-filter").value = "no-match";
    f.elements.get("candidate-search-form").requestSubmit();
    await f.wait(() => f.elements.get("candidate-list").textContent.includes("No candidates"), "Synthetic empty search must render");
    f.elements.get("candidate-filter").value = "simulate-error";
    f.elements.get("candidate-search-form").requestSubmit();
    await f.wait(() => f.elements.get("notice").className.includes("error"), "Synthetic error must render");
    assert.doesNotMatch(f.elements.get("notice").textContent, /SYNTHETIC_PRIVATE_MESSAGE/);
    f.elements.get("organization-select").value = "00000002-1111-4111-8111-111111111111";
    f.elements.get("organization-select").emit("change");
    await f.wait(() => f.elements.get("organization-heading").textContent === "Empty workspace", "Synthetic organization must switch");
    assert.doesNotMatch(heading.textContent, /Alex Morgan/);
    f.elements.get("logout").click();
    assert.equal(f.elements.get("shell").hidden, true);
    assert.equal(f.elements.get("account-email").textContent, "");
    assert.equal(f.elements.get("auth-password").value, "");
  } finally { await f.restore(); }
});
