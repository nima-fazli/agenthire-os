import {
  $,
  auth,
  apiClient,
  button,
  clear,
  el,
  message,
  pill,
  showSignedOut,
  syncCards,
  task,
} from "./agent-ui.mjs";
let signedIn = false,
  verified = false,
  revision = 0,
  timer = null,
  selectedJob = null,
  offset = 0,
  questionRun = null;
const api = apiClient(signOut),
  mode = () => $("portal-mode").value;
function signOut() {
  revision++;
  signedIn = false;
  verified = false;
  questionRun = null;
  clearInterval(timer);
  timer = null;
  for (const id of [
    "portal-applications",
    "portal-notifications",
    "portal-assistant-result",
    "portal-assistant-application",
  ])
    clear($(id));
  for (const id of [
    "portal-name",
    "portal-resume",
    "portal-code",
    "portal-pdf",
  ])
    $(id).value = "";
  $("portal-apply").hidden = true;
  $("portal-mode").value = "replay";
  showSignedOut();
  task(loadJobs);
}
async function loadJobs() {
  const current = revision;
  const result = await api(`/public/jobs?offset=${offset}`);
  if (current !== revision) return;
  clear($("portal-jobs"));
  for (const job of result.items) {
    const card = el("article", undefined, "agent-item");
    card.append(
      el("h3", job.title),
      el("p", job.company, "agent-meta"),
      el("p", job.description),
    );
    card.append(
      button("Choose this opportunity", async () => {
        selectedJob = job.id;
        $("portal-selected-job").textContent =
          `Selected opportunity: ${job.title} · ${job.company}`;
        message(
          signedIn
            ? verified
              ? "Paste a resume or select a PDF, then submit."
              : "Verify your email before applying."
            : "Sign in or create an individual applicant account. No company is needed.",
        );
        const target = signedIn
          ? $(verified ? "portal-apply" : "portal-verification")
          : $("agent-auth");
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      }),
    );
    $("portal-jobs").append(card);
  }
  if (!result.items.length)
    $("portal-jobs").append(
      el(
        "p",
        "No published opportunities yet. The employer can publish a job in Agent Center.",
        "agent-empty",
      ),
    );
  $("portal-next").disabled = !result.has_more;
  $("portal-previous").disabled = offset === 0;
}
async function refresh() {
  if (!signedIn) return;
  const current = revision;
  const [applications, notices] = await Promise.all([
    api("/portal/api/applications"),
    api("/portal/api/notifications"),
  ]);
  if (current !== revision) return;
  syncCards($("portal-applications"), applications, (a) => {
    const card = el("article", undefined, "agent-item");
    card.append(el("h3", a.job_title), pill(a.status));
    if (a.question)
      card.append(
        el("h3", "Employer-approved question"),
        el("p", a.question, "agent-quote"),
      );
    if (
      a.question_revision > a.answered_revision &&
      !["Hired", "Not selected"].includes(a.status)
    ) {
      const form = el("form", undefined, "agent-form"),
        label = el("label", "Your clarification"),
        text = el("textarea");
      text.required = true;
      text.minLength = 5;
      text.maxLength = 10000;
      label.append(text);
      const send = el("button", "Send answer", "agent-button");
      send.type = "submit";
      form.append(label, send);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        task(async () => {
          await api(`/portal/api/applications/${a.id}/answer`, {
            method: "POST",
            data: {
              question_revision: a.question_revision,
              text: text.value,
              mode: mode(),
            },
          });
          message("Answer saved. A fresh review was queued for the employer.");
          await refresh();
        }, send);
      });
      card.append(form);
    } else if (a.question_revision)
      card.append(
        el("p", "Your clarification has been received.", "agent-meta"),
      );
    if (a.state === "draft")
      card.append(
        el(
          "p",
          "Draft only. Choose the same job and resubmit to finish it.",
          "agent-meta",
        ),
      );
    return card;
  });
  const select = $("portal-assistant-application"),
    selected = select.value,
    submitted = applications.filter((a) => a.state === "submitted"),
    signature = JSON.stringify(submitted.map((a) => [a.id, a.job_title]));
  if (select.dataset.signature !== signature) {
    select.dataset.signature = signature;
    clear(select);
    for (const a of submitted) {
      const option = el("option", a.job_title);
      option.value = a.id;
      select.append(option);
    }
    if (submitted.some((a) => a.id === selected)) select.value = selected;
  }
  syncCards($("portal-notifications"), notices, (n) => {
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
  if (questionRun) {
    const id = questionRun,
      result = await api(`/portal/api/agent-runs/${id}`);
    if (current !== revision || questionRun !== id) return;
    const root = $("portal-assistant-result"),
      sig = JSON.stringify(result);
    if (root.dataset.signature !== sig) {
      root.dataset.signature = sig;
      clear(root);
      root.append(pill(`${result.mode} · ${result.status}`));
      if (result.answer) root.append(el("p", result.answer, "agent-quote"));
      else
        root.append(
          el(
            "p",
            result.message ||
              "The assistant is working. This page checks its progress automatically.",
            "agent-meta",
          ),
        );
    }
    if (["completed", "failed", "cancelled"].includes(result.status))
      questionRun = null;
  }
}
async function ready() {
  revision++;
  signedIn = true;
  const current = revision;
  const info = await api("/portal/api/verification");
  if (current !== revision) return;
  verified = info.verified;
  $("portal-verification").hidden = verified;
  $("portal-apply").hidden = !verified;
  await Promise.all([loadJobs(), refresh()]);
  clearInterval(timer);
  timer = setInterval(() => task(refresh), 3500);
}
auth(api, ready, signOut, true);
$("portal-request-code").addEventListener("click", () =>
  task(async () => {
    await api("/portal/api/verification/request", { method: "POST" });
    message(
      "Code queued. Open the local Mailpit inbox, find your address and enter its six-digit code here.",
    );
  }, $("portal-request-code")),
);
$("portal-verify-form").addEventListener("submit", (event) => {
  event.preventDefault();
  task(async () => {
    await api("/portal/api/verification/confirm", {
      method: "POST",
      data: { code: $("portal-code").value },
    });
    $("portal-code").value = "";
    verified = true;
    $("portal-verification").hidden = true;
    $("portal-apply").hidden = false;
    message("Email verified. You can apply without creating a company.");
  }, $("portal-confirm-code"));
});
$("portal-apply-form").addEventListener("submit", (event) => {
  event.preventDefault();
  task(async () => {
    if (!selectedJob) throw new Error("Choose a public opportunity first.");
    const file = $("portal-pdf").files[0];
    if (
      file &&
      (!file.size ||
        file.size > 5 * 1024 * 1024 ||
        !file.name.toLowerCase().endsWith(".pdf"))
    )
      throw new Error("Choose a nonempty PDF of at most 5 MiB.");
    const draft = await api("/portal/api/drafts", {
      method: "POST",
      data: {
        job_id: selectedJob,
        full_name: $("portal-name").value,
        resume_text: $("portal-resume").value,
      },
    });
    if (file)
      await api(
        `/portal/api/applications/${draft.id}/resume?filename=${encodeURIComponent(file.name)}`,
        { method: "PUT", body: file },
      );
    await api(`/portal/api/applications/${draft.id}/submit`, {
      method: "POST",
      data: { mode: mode() },
    });
    $("portal-name").value = "";
    $("portal-resume").value = "";
    $("portal-pdf").value = "";
    message("Application received. Its receipt and review are queued.");
    await refresh();
  }, $("portal-submit"));
});
$("portal-ask-form").addEventListener("submit", (event) => {
  event.preventDefault();
  task(async () => {
    const id = $("portal-assistant-application").value;
    if (!id)
      throw new Error("Submit an application before asking its assistant.");
    const result = await api(`/portal/api/applications/${id}/ask`, {
      method: "POST",
      data: { goal: $("portal-goal").value, mode: mode() },
    });
    questionRun = result.id;
    $("portal-assistant-result").dataset.signature = "";
    await refresh();
  }, $("portal-ask"));
});
$("portal-next").addEventListener("click", () =>
  task(async () => {
    offset += 20;
    await loadJobs();
  }, $("portal-next")),
);
$("portal-previous").addEventListener("click", () =>
  task(async () => {
    offset = Math.max(0, offset - 20);
    await loadJobs();
  }, $("portal-previous")),
);
window.addEventListener("pagehide", () => clearInterval(timer));
task(loadJobs);
