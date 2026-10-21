import {
  $,
  auth,
  apiClient,
  button,
  clear,
  el,
  fact,
  message,
  pill,
  reportView,
  showSignedOut,
  syncCards,
  task,
} from "./agent-ui.mjs";
let organization = null,
  canWrite = false,
  revision = 0,
  timer = null,
  activeRun = null,
  jobSignature = "";
const api = apiClient(signOut);
const path = (suffix) => `/organizations/${organization}/${suffix}`;
function signOut() {
  revision++;
  organization = null;
  activeRun = null;
  clearInterval(timer);
  timer = null;
  for (const id of [
    "agent-organizations",
    "agent-submissions",
    "agent-runs",
    "agent-run-detail",
    "agent-notifications",
    "agent-mail-status",
    "agent-jobs",
  ])
    clear($(id));
  showSignedOut();
}
function mode() {
  return $("agent-mode").value;
}
async function refresh() {
  if (!organization) return;
  const current = revision,
    oid = organization;
  const [access, jobs, submissions, runs, notices, mail] = await Promise.all([
    api(path("access")),
    api(path("jobs")),
    api(path("applicant-submissions")),
    api(path("agent-runs")),
    api(path("agent-notifications")),
    api(path("agent-mail-status")),
  ]);
  if (current !== revision || organization !== oid) return;
  canWrite = access.can_write;
  $("agent-role").textContent =
    `${access.role} · ${canWrite ? "Can review and approve" : "Read only"}`;
  $("agent-publish").disabled = !canWrite;
  $("agent-mail-retry").disabled = !canWrite;
  const sig = JSON.stringify(jobs);
  if (sig !== jobSignature) {
    jobSignature = sig;
    const selected = $("agent-jobs").value;
    clear($("agent-jobs"));
    for (const j of jobs) {
      const option = el("option", j.title);
      option.value = j.id;
      $("agent-jobs").append(option);
    }
    if (jobs.some((x) => x.id === selected)) $("agent-jobs").value = selected;
    if (!selected && jobs.length) await loadPublication();
  }
  syncCards($("agent-submissions"), submissions, (item) => {
    const card = el("article", undefined, "agent-item");
    card.append(
      el("h3", item.full_name),
      el("p", item.job_title, "agent-meta"),
      pill(item.status),
    );
    const start = button("Start review", async () => {
      await api(path(`applicant-submissions/${item.id}/agent-runs`), {
        method: "POST",
        data: { mode: mode() },
      });
      message("Review queued. Follow its tool steps in Agent runs.");
      await refresh();
    });
    start.disabled = !canWrite;
    const actions = el("div", undefined, "agent-actions");
    actions.append(start);
    card.append(actions);
    return card;
  });
  syncCards($("agent-runs"), runs, (item) => {
    const card = el("article", undefined, "agent-item");
    card.append(
      el("h3", `${item.kind} review`),
      pill(`${item.mode} · ${item.status}`),
      el("p", `${item.model} · ${item.steps} tool steps`, "agent-meta"),
      button("Inspect run", () => inspect(item.id)),
    );
    return card;
  });
  syncCards($("agent-notifications"), notices, (n) => {
    const card = el("article", undefined, "agent-item");
    card.append(el("h3", n.title), el("p", n.body));
    if (!n.read_at)
      card.append(
        button("Mark read", async () => {
          await api(`/portal/api/notifications/${n.id}/read`, {
            method: "POST",
          });
          await refresh();
        }),
      );
    return card;
  });
  syncCards($("agent-mail-status"), mail, (item) => {
    const card = el("article", undefined, "agent-item");
    card.append(
      el("h3", item.subject),
      el("p", item.recipient, "agent-meta"),
      pill(item.status),
    );
    if (item.failure_code)
      card.append(el("p", item.failure_code, "agent-meta"));
    return card;
  });
  if (activeRun) {
    const item = runs.find((r) => r.id === activeRun);
    if (item && ["queued", "running"].includes(item.status))
      await inspect(activeRun, false);
    else if (item && $("agent-run-detail").dataset.status !== item.status)
      await inspect(activeRun, false);
  }
}
async function inspect(id, focus = true) {
  const current = revision;
  const run = await api(path(`agent-runs/${id}`));
  if (current !== revision) return;
  activeRun = id;
  const root = $("agent-run-detail");
  clear(root);
  root.dataset.status = run.status;
  root.append(
    el("h2", "Run details"),
    pill(`${run.mode} · ${run.status}`),
    el("p", run.goal, "agent-meta"),
  );
  const facts = el("div", undefined, "agent-facts");
  facts.append(
    fact("Tool steps", run.steps),
    fact("Model tokens", run.input_tokens + run.output_tokens),
    fact("Recorded inference", `${(run.elapsed_ms / 1000).toFixed(1)} s`),
  );
  root.append(facts);
  if (run.mode === "replay")
    root.append(
      el(
        "p",
        "Replay is deterministic. No model inference was performed.",
        "agent-banner",
      ),
    );
  if (run.failure_code)
    root.append(
      el(
        "p",
        `Run stopped: ${run.failure_code}. Start a new review after resolving the cause.`,
        "agent-message is-error",
      ),
    );
  if (run.model_digest)
    root.append(
      el("p", `Observed model digest: ${run.model_digest}`, "agent-meta"),
    );
  if (run.report?.findings) root.append(reportView(run.report));
  const actions = el("div", undefined, "agent-actions");
  if (run.status === "waiting_approval" && canWrite) {
    actions.append(
      button(
        run.report.question
          ? "Approve & queue this question"
          : "Approve reviewed findings",
        async () => {
          await api(path(`agent-runs/${id}/approval`), {
            method: "POST",
            data: {
              decision: "approve",
              source_fingerprint: run.source_fingerprint,
            },
          });
          message(
            "Review approved. Any approved clarification is queued for local delivery.",
          );
          await inspect(id, false);
          await refresh();
        },
        false,
      ),
      button("Dismiss", async () => {
        await api(path(`agent-runs/${id}/approval`), {
          method: "POST",
          data: {
            decision: "dismiss",
            source_fingerprint: run.source_fingerprint,
          },
        });
        await inspect(id, false);
        await refresh();
      }),
    );
  }
  if (["queued", "running"].includes(run.status) && canWrite)
    actions.append(
      button("Cancel run", async () => {
        await api(path(`agent-runs/${id}/cancel`), { method: "POST" });
        await inspect(id, false);
        await refresh();
      }),
    );
  root.append(actions);
  root.append(el("h3", "Tool timeline"));
  for (const event of run.events) {
    const details = el("details", undefined, "agent-trace");
    details.append(
      el("summary", `${event.sequence}. ${event.payload.tool || event.type}`),
      el("pre", JSON.stringify(event.payload, null, 2)),
    );
    root.append(details);
  }
  if (focus) {
    root.scrollIntoView({ behavior: "smooth", block: "start" });
    root.focus({ preventScroll: true });
  }
}
async function loadPublication() {
  if (!organization || !$("agent-jobs").value) return;
  const current = revision,
    jid = $("agent-jobs").value;
  const p = await api(path(`career-publications/${jid}`));
  if (current !== revision || jid !== $("agent-jobs").value) return;
  $("agent-public-description").value = p.public_description;
  $("agent-published").checked = p.published;
}
async function chooseOrganization() {
  revision++;
  organization = $("agent-organizations").value || null;
  activeRun = null;
  jobSignature = "";
  for (const id of [
    "agent-submissions",
    "agent-runs",
    "agent-run-detail",
    "agent-notifications",
    "agent-mail-status",
    "agent-jobs",
  ])
    clear($(id));
  await refresh();
}
auth(
  api,
  async () => {
    const organizations = await api("/organizations");
    clear($("agent-organizations"));
    for (const org of organizations) {
      const option = el("option", org.name);
      option.value = org.id;
      $("agent-organizations").append(option);
    }
    if (!organizations.length) {
      message(
        "You do not belong to a company. Applicants can use Applicant Portal without creating one.",
      );
      return;
    }
    await chooseOrganization();
    clearInterval(timer);
    timer = setInterval(() => task(refresh), 3500);
  },
  signOut,
);
$("agent-organizations").addEventListener("change", () =>
  task(chooseOrganization),
);
$("agent-jobs").addEventListener("change", () => task(loadPublication));
$("agent-publication-form").addEventListener("submit", (event) => {
  event.preventDefault();
  task(async () => {
    await api(path(`career-publications/${$("agent-jobs").value}`), {
      method: "PUT",
      data: {
        published: $("agent-published").checked,
        public_description: $("agent-public-description").value,
      },
    });
    message("Public job description saved. Internal criteria stay private.");
  }, $("agent-publish"));
});
$("agent-mail-retry").addEventListener("click", () =>
  task(async () => {
    const result = await api(path("agent-mail-retry"), { method: "POST" });
    message(`${result.queued} failed deliveries queued again.`);
    await refresh();
  }, $("agent-mail-retry")),
);
$("agent-refresh").addEventListener("click", () =>
  task(refresh, $("agent-refresh")),
);
window.addEventListener("pagehide", () => clearInterval(timer));
