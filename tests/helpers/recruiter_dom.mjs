import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

export class Element extends EventTarget {
  constructor(tag = "div") {
    super();
    this.tag = tag; this.tagName = tag.toUpperCase();
    this.children = []; this.value = ""; this.disabled = false;
    this.hidden = false; this.checked = false; this.open = false;
    this.isConnected = true;
  }
  set textContent(text) { this.text = String(text); this.children = []; }
  get textContent() { return (this.text ?? "") + this.children.map(child => child.textContent).join(""); }
  set innerHTML(_value) { assert.fail("HTML injection sink"); }
  append(...items) { for (const item of items) { item.parent = this; this.children.push(item); } }
  replaceChildren(...items) { this.text = ""; this.children = []; this.append(...items); }
  contains(item) { return item === this || this.children.some(child => child.contains(item)); }
  remove() {
    this.isConnected = false;
    if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this);
  }
  reset() {}
  focus() { if (globalThis.document) globalThis.document.activeElement = this; }
  click() { this.emit("click"); }
  emit(type) { this.dispatchEvent(new Event(type, { cancelable: true })); }
  showModal() { this.open = true; }
  close(value) { this.returnValue = value; this.open = false; this.emit("close"); }
}

export const visit = element => [element, ...element.children.flatMap(visit)];
export const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { "Content-Type": "application/json" },
});
export function pageResponse(data, path) {
  const query = new URL(path, "http://fixture").searchParams;
  const offset = Number(query.get("offset") ?? 0), limit = Number(query.get("limit") ?? 20);
  return json({ items: data.slice(offset, offset + limit), total: data.length, offset, limit });
}

export function installDOM() {
  const saved = { document: globalThis.document, window: globalThis.window, fetch: globalThis.fetch };
  const html = readFileSync(new URL("../../app/web/assets/index.html", import.meta.url), "utf8");
  const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(match => [match[1], new Element()]));
  const document = {
    getElementById: key => elements.get(key), createElement: tag => new Element(tag),
    createDocumentFragment: () => new Element("fragment"),
    createTextNode: text => { const value = new Element("#text"); value.textContent = text; return value; },
    body: new Element("body"), activeElement: null,
  };
  globalThis.document = document;
  globalThis.window = new EventTarget();
  elements.get("retrieval-mode").value = "lexical";
  return {
    elements, document,
    async wait(condition, label = "Expected UI state") {
      const deadline = performance.now() + 5000;
      while (performance.now() < deadline) {
        if (condition()) return;
        await new Promise(resolve => setTimeout(resolve, 10));
      }
      assert.fail(`${label}; notice: ${elements.get("notice").textContent}`);
    },
    async restore() {
      globalThis.window.dispatchEvent(new Event("pagehide"));
      await new Promise(resolve => setTimeout(resolve, 0));
      globalThis.document = saved.document; globalThis.window = saved.window; globalThis.fetch = saved.fetch;
    },
  };
}
