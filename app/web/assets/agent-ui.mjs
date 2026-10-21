export const $ = (id) => document.getElementById(id);
export function el(tag, text, className) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (className) n.className = className;
  return n;
}
export const clear = (n) => n.replaceChildren();
export function message(text, error = false) {
  const n = $("agent-message");
  n.textContent = text;
  n.classList.toggle("is-error", error);
  n.setAttribute("role", error ? "alert" : "status");
}
export async function task(action, control) {
  if (control?.disabled) return;
  if (control) control.disabled = true;
  try {
    await action();
  } catch (error) {
    if (error.name !== "AbortError") message(error.message, true);
  } finally {
    if (control?.isConnected) control.disabled = false;
  }
}
export function button(text, action, secondary = true) {
  const n = el(
    "button",
    text,
    secondary ? "agent-button secondary" : "agent-button",
  );
  n.type = "button";
  n.addEventListener("click", () => task(action, n));
  return n;
}
export const pill = (text) =>
  el("span", String(text).replaceAll("_", " "), "agent-pill");
export function fact(label, value) {
  const n = el("div", undefined, "agent-fact");
  n.append(el("span", label), el("strong", String(value)));
  return n;
}
const help = {
  AGENTS_DISABLED:
    "Start the stack with compose.agents.yaml to enable agent services.",
  EMAIL_VERIFICATION_REQUIRED:
    "Verify your email using the code captured in Mailpit.",
  MODEL_NOT_INSTALLED:
    "Install the configured local model using the Live AI setup guide.",
  REVIEW_STALE: "Sources or criteria changed. Start a fresh review.",
  JOB_CRITERIA_REQUIRED:
    "Save job criteria in the recruiting workspace before starting a review.",
  APPLICATION_ALREADY_SUBMITTED:
    "You already applied. Track this job in My applications.",
  VERIFICATION_INVALID:
    "The code is incorrect, unavailable or expired. Request a new code if needed.",
  VERIFICATION_THROTTLED: "Wait one minute before requesting another code.",
  RESUME_REQUIRED:
    "Upload a PDF or paste at least 40 characters of resume text.",
  SUBMISSION_IMMUTABLE: "A submitted resume cannot be replaced.",
  PERMISSION_DENIED: "Your role does not allow this action.",
};
export function apiClient(onExpired, timeoutMs = 65000) {
  let token = null,
    epoch = 0;
  const pending = new Set();
  const api = async (path, { method = "GET", data, body } = {}) => {
    if (
      !path.startsWith("/") ||
      path.startsWith("//") ||
      path.includes("\\") ||
      /[\x00-\x20\x7f#]/.test(path)
    )
      throw new Error("Invalid API path.");
    const controller = new AbortController(),
      current = epoch;
    pending.add(controller);
    let timedOut = false;
    const cancelled = new Promise((_, reject) =>
      controller.signal.addEventListener(
        "abort",
        () =>
          reject(
            timedOut
              ? new Error(
                  "The request timed out. Check the service and try again.",
                )
              : new DOMException("Context changed", "AbortError"),
          ),
        { once: true },
      ),
    );
    const bounded = (p) => Promise.race([p, cancelled]);
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    try {
      const headers = { Accept: "application/json" };
      if (token) headers.Authorization = `Bearer ${token}`;
      if (data !== undefined) headers["Content-Type"] = "application/json";
      if (body !== undefined) headers["Content-Type"] = "application/pdf";
      const response = await bounded(
        fetch(path, {
          method,
          headers,
          body: data !== undefined ? JSON.stringify(data) : body,
          signal: controller.signal,
          cache: "no-store",
          credentials: "omit",
          redirect: "error",
        }),
      );
      if (current !== epoch)
        throw new DOMException("Context changed", "AbortError");
      const value = await bounded(response.json());
      if (current !== epoch)
        throw new DOMException("Context changed", "AbortError");
      if (!response.ok) {
        if (response.status === 401 && token) {
          api.reset();
          onExpired();
        }
        const code = value?.error?.code;
        throw new Error(
          Object.hasOwn(help, code)
            ? help[code]
            : "The request could not be completed" +
              (/^[A-Z0-9_]{1,70}$/.test(code || "") ? ` (${code}).` : "."),
        );
      }
      return value;
    } finally {
      clearTimeout(timer);
      pending.delete(controller);
    }
  };
  api.reset = () => {
    epoch++;
    token = null;
    for (const c of pending) c.abort();
    pending.clear();
  };
  api.setToken = (value) => {
    api.reset();
    token = value;
  };
  return api;
}
export function showSignedOut() {
  $("agent-auth").hidden = false;
  $("agent-private").hidden = true;
  $("agent-logout").hidden = true;
}
export function auth(api, ready, signedOut, allowRegister = false) {
  let register = false;
  $("agent-auth-form").addEventListener("submit", (event) => {
    event.preventDefault();
    task(async () => {
      const email = $("agent-email").value.trim(),
        password = $("agent-password").value;
      if (register)
        await api("/users/register", {
          method: "POST",
          data: { email, password },
        });
      const result = await api("/auth/login", {
        method: "POST",
        data: { email, password },
      });
      api.setToken(result.access_token);
      $("agent-password").value = "";
      $("agent-auth").hidden = true;
      $("agent-private").hidden = false;
      $("agent-logout").hidden = false;
      message(
        register
          ? "Account created. Verify your email to apply."
          : "Signed in.",
      );
      await ready();
    }, $("agent-login"));
  });
  if (allowRegister)
    $("agent-register").addEventListener("click", () => {
      register = !register;
      $("agent-auth-title").textContent = register
        ? "Create an applicant account"
        : "Sign in";
      $("agent-login").textContent = register ? "Create account" : "Sign in";
      $("agent-register").textContent = register
        ? "Use an existing account"
        : "Create an account";
      $("agent-password").minLength = register ? 15 : 1;
      $("agent-password").autocomplete = register
        ? "new-password"
        : "current-password";
    });
  $("agent-logout").addEventListener("click", () =>
    task(async () => {
      try {
        await api("/auth/logout", { method: "POST" });
      } finally {
        api.reset();
        signedOut();
        message("Signed out.");
      }
    }),
  );
}
export function syncCards(container, items, render) {
  const ids = new Set(items.map((x) => String(x.id)));
  for (const n of [...container.children])
    if (n.dataset.itemId && !ids.has(n.dataset.itemId)) n.remove();
  if (!items.length) {
    if (!container.querySelector(".agent-empty")) {
      clear(container);
      container.append(el("p", "Nothing here yet.", "agent-empty"));
    }
    return;
  }
  container.querySelector(".agent-empty")?.remove();
  for (const item of items) {
    const id = String(item.id),
      signature = JSON.stringify(item);
    let old = [...container.children].find((n) => n.dataset.itemId === id);
    if (old?.dataset.signature === signature) continue;
    const n = render(item);
    n.dataset.itemId = id;
    n.dataset.signature = signature;
    if (old) old.replaceWith(n);
    else container.append(n);
  }
}
export function reportView(report) {
  const root = el("div");
  root.append(el("h3", "Review summary"), el("p", report.summary));
  for (const f of report.findings) {
    const card = el("section", undefined, "agent-item");
    card.append(el("h3", f.label), pill(f.assessment));
    for (const c of f.citations) {
      const details = el("details");
      details.append(
        el("summary", "View source excerpt"),
        el("blockquote", c.quote, "agent-quote"),
        el(
          "p",
          `${c.source_id} · Unicode offsets ${c.start}–${c.end}`,
          "agent-meta",
        ),
      );
      card.append(details);
    }
    root.append(card);
  }
  if (report.question)
    root.append(
      el("h3", "Proposed clarification"),
      el("p", report.question, "agent-quote"),
    );
  root.append(el("p", report.notice, "agent-meta"));
  return root;
}
