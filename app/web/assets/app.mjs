import { $, empty, notice, setupNotices } from "./dom.mjs";
import { ApiClient, ApiError } from "./api.mjs";
import { Session, candidatePath } from "./session.mjs";
import { RequestGate } from "./requests.mjs";
import { createWorkspace } from "./workspace.mjs";
import { createProfiles } from "./profiles.mjs";
import { createCandidates } from "./candidates.mjs";
import { createEvidence } from "./evidence.mjs";
import { createNotifications } from "./notifications.mjs";

setupNotices(createNotifications({
  region: $("notification"),
  status: $("notice"),
  alert: $("notice-alert"),
  dismiss: $("notice-dismiss"),
}));

const session = new Session();
const gate = new RequestGate();
const pending = new Map();

let registering = false;
let authAttempt = 0;

const ctx = {
  session,
  gate,
  profilesReady: false,
  api: new ApiClient(
    () => session.token,
    () => logout("نشست پایان یافته است؛ دوباره وارد شوید."),
  ),
};

ctx.sync = () => {
  const org = session.organization;
  const job = session.job;
  const candidate = session.candidate;

  const state = (id, blocked, key) => {
    $(id).disabled = Boolean(blocked || pending.has(key));
  };

  state("auth-fields", pending.has("identity"), "authentication");
  state("auth-mode", $("auth-fields").disabled);
  state("workspace-refresh", !org, "organization");
  state("job-create", !org, "job-create");
  state("candidate-create", !org, "candidate-create");
  state("organization-create", false, "organization-create");

  state("profiles-fields", !job || !ctx.profilesReady, "profiles");
  state("search-save", !job || !ctx.profilesReady, "search-save");
  state("match-save", !job || !ctx.profilesReady, "profile-save");

  state("retrieval-run", !job || !ctx.profilesReady, "retrieval");
  state("retrieval-cancel", !pending.has("retrieval"));
  state("candidate-fields", !candidate);

  state("evidence-load", !job || !candidate, "evidence");
  state("explanation-run", !job || !candidate, "explanation");
  state("explanation-cancel", !pending.has("explanation"));

  state("document-upload", !candidate, "upload");
  state("documents-refresh", !candidate, "documents");

  for (const item of pending.values()) {
    if (item.control) item.control.disabled = true;
  }
};

ctx.cancel = (...keys) => {
  for (const key of keys) {
    gate.cancel(key);
    const item = pending.get(key);
    pending.delete(key);

    if (item?.control) item.control.disabled = false;
  }

  ctx.sync();
};

ctx.cancelAll = () => {
  ctx.cancel(...pending.keys());
  gate.reset();
};

ctx.perform = async (
  key,
  work,
  done = () => {},
  control = null,
  mutation = false,
) => {
  if (mutation && (pending.has(key) || gate.has(key))) return null;

  ctx.cancel(key);

  const item = { control };
  const epoch = gate.epoch;
  pending.set(key, item);

  const current = () =>
    epoch === gate.epoch && pending.get(key) === item;

  if (control) control.disabled = true;

  try {
    const task = gate.run(key, work, !mutation);
    ctx.sync();

    const value = await task;

    if (!current()) return null;

    await done(value, current);
    return true;
  } catch (error) {
    if (error.name === "AbortError" || !current()) return null;

    notice(
      error instanceof ApiError
        ? error.message
        : "پاسخ قابل استفاده نبود؛ وضعیت را تازه‌سازی کنید.",
      true,
    );

    return false;
  } finally {
    if (pending.get(key) === item) {
      pending.delete(key);
      if (control) control.disabled = false;
    }

    ctx.sync();
  }
};

ctx.invalidateEvidence = () => {
  ctx.candidates.clearResults();
  ctx.evidence.clearResults();
};

ctx.profileChanged = () => {
  ctx.invalidateEvidence();
  notice("اطلاعات ثبت شد؛ شواهد و بازیابی را دوباره بخوانید.");
};

ctx.selectOrganization = async item => {
  ctx.cancelAll();
  session.selectOrganization(item);

  ctx.profiles.reset();
  ctx.candidates.reset();
  ctx.evidence.reset();
  ctx.workspace.clearOrganization();
  ctx.sync();

  notice(
    item
      ? "در حال دریافت فهرست‌های سازمان…"
      : "برای شروع، سازمان بسازید یا انتخاب کنید.",
  );

  if (item) await ctx.workspace.loadOrganization();
};

ctx.selectJob = async item => {
  ctx.cancel(
    "profiles",
    "profile-save",
    "search-save",
    "retrieval",
    "evidence",
    "explanation",
    "candidate",
  );

  session.selectJob(item);
  ctx.profiles.reset();
  ctx.invalidateEvidence();
  ctx.workspace.showJob(item);
  ctx.sync();

  if (item && !(await ctx.profiles.load())) return;

  if (!item && !session.job) {
    notice("یک شغل بسازید یا انتخاب کنید.");
  }
};

ctx.selectCandidate = async item => {
  ctx.cancel("candidate");
  ctx.evidence.reset();
  session.selectCandidate(item);
  ctx.sync();

  if (item) return ctx.evidence.selectCandidate(item);
};

ctx.selectCandidateId = async id => {
  const org = session.organization;

  if (org) {
    await ctx.perform(
      "candidate",
      signal => ctx.api.request(candidatePath(org.id, id), { signal }),
      ctx.selectCandidate,
    );
  }
};

ctx.workspace = createWorkspace(ctx);
ctx.profiles = createProfiles(ctx);
ctx.candidates = createCandidates(ctx);
ctx.evidence = createEvidence(ctx);

function setAuthMode(value) {
  registering = value;

  $("auth-title").textContent =
    value ? "ساخت حساب" : "ورود به فضای کاری";

  $("auth-description").textContent = value
    ? "رمز عبور حساب جدید باید حداقل ۱۵ کاراکتر داشته باشد."
    : "با حساب خود، سازمان و پرونده‌های در دسترس را انتخاب کنید.";

  $("auth-submit").textContent = value ? "ثبت‌نام" : "ورود";
  $("auth-mode").textContent =
    value ? "حساب دارم؛ ورود" : "حساب ندارم؛ ثبت‌نام";

  $("auth-password").minLength = value ? 15 : 1;
  $("auth-password").autocomplete =
    value ? "new-password" : "current-password";
}

function logout(message = "از حساب خارج شدید.") {
  authAttempt += 1;
  ctx.cancelAll();
  session.clear();

  ctx.workspace.reset();
  ctx.profiles.reset();
  ctx.candidates.reset();
  ctx.evidence.reset();

  $("shell").hidden = $("account").hidden = true;
  $("auth-view").hidden = $("public-label").hidden = false;
  $("account-email").textContent = "";
  $("auth-form").reset();
  $("auth-password").value = "";

  setAuthMode(false);
  ctx.sync();
  notice(message);
}

$("auth-mode").addEventListener("click", () => {
  setAuthMode(!registering);
});

$("logout").addEventListener("click", () => {
  logout();
  $("auth-email").focus();
});

$("auth-form").addEventListener("submit", async event => {
  event.preventDefault();

  if (pending.has("authentication") || pending.has("identity")) return;

  const mode = registering;
  const attempt = ++authAttempt;
  const data = {
    email: $("auth-email").value.trim(),
    password: $("auth-password").value,
  };

  notice(mode ? "در حال ساخت حساب…" : "در حال ورود…");

  await ctx.perform(
    "authentication",
    signal => ctx.api.request(
      mode ? "/users/register" : "/auth/login",
      { method: "POST", data, signal },
    ),
    async result => {
      if (attempt !== authAttempt) return;

      $("auth-password").value = "";

      if (mode) {
        setAuthMode(false);
        notice("حساب ساخته شد؛ با رمز خود وارد شوید.");
        return;
      }

      session.authenticate(result.access_token);

      const identified = await ctx.perform(
        "identity",
        signal => ctx.api.request("/users/me", { signal }),
        async user => {
          session.identify(user);
          $("account-email").textContent = user.email;
          $("auth-view").hidden = $("public-label").hidden = true;
          $("shell").hidden = $("account").hidden = false;
          await ctx.workspace.loadOrganizations();
        },
      );

      if (identified === false && attempt === authAttempt) {
        logout("ورود کامل نشد؛ دوباره وارد شوید.");
      }
    },
    $("auth-fields"),
    true,
  );

  if (attempt === authAttempt) $("auth-password").value = "";
});

window.addEventListener("pagehide", () => logout(""));

window.addEventListener("offline", () => {
  notice(
    "اتصال قطع شده است؛ تغییر تازه‌ای به سرور ارسال نکنید.",
    true,
  );
});

empty($("job-description-view"), "یک شغل انتخاب کنید.");
logout("");
