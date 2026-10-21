import { $, node, button, empty, field } from "./dom.mjs";
import { createPager, mutationNotice } from "./paging.mjs";
import { orgPath, uuid } from "./session.mjs";
import { avatar, applicationStatus } from "./ui.mjs";

export const applicationLabels = Object.freeze({
  applied: "Applied", screening: "Screening", interview: "Interview",
  offer: "Offer", hired: "Hired", rejected: "Rejected",
});

export function createApplications(ctx) {
  const pager = createPager(ctx, {
    name: "application",
    url: () => ctx.session.job ? `${orgPath(ctx.session.organization.id)}/recruiting/applications` : null,
    filters: () => ({ q: $("application-filter").value.trim(), status: $("application-status-filter").value,
      job_id: ctx.session.job.id }),
    clear: text => {
      empty($("application-list"), text);
      for (const id of ["applications-count", "interviews-count", "offers-count"]) $(id).textContent = "—";
    },
    render(page) {
      const org = ctx.session.organization, job = ctx.session.job;
      const content = document.createDocumentFragment();
      for (const item of page.items) {
        uuid(item.id); uuid(item.candidate_id);
        if (item.organization_id !== org.id || item.job_id !== job.id
            || !Object.hasOwn(applicationLabels, item.status) || !Array.isArray(item.allowed_statuses)
            || item.allowed_statuses.some(value => !Object.hasOwn(applicationLabels, value)))
          throw new Error("INVALID_SCOPE");
        const card = node("article", "", "application-card");
        const title = node("h3", item.candidate_name);
        title.dir = "auto";
        const person = node("div", "", "application-person");
        const identity = node("div", "", "candidate-identity");
        identity.append(title, node("p", item.job_title, "small muted"));
        person.append(avatar({ full_name: item.candidate_name, synthetic_portrait: item.synthetic_portrait }), identity);
        card.append(person, applicationStatus(item.status, applicationLabels[item.status]));
        card.append(button("Open candidate", () => ctx.selectCandidateId(item.candidate_id)));
        if (item.allowed_statuses.length) {
          const select = field("Next status", { value: "",
            options: [["", "Select a status"], ...item.allowed_statuses.map(value => [value, applicationLabels[value]])] });
          select.input.requiresWrite = true;
          const save = button("Update status", async () => {
            const target = select.input.value;
            if (!item.allowed_statuses.includes(target)) return;
            const accepted = await ctx.confirm.ask({ title: "Confirm status change",
              message: `${item.candidate_name} · ${item.job_title}: ${applicationLabels[item.status]} → ${applicationLabels[target]}` });
            if (!accepted || ctx.session.organization?.id !== org.id || ctx.session.job?.id !== job.id) return;
            await ctx.perform("application-transition", signal => ctx.api.request(
              `${orgPath(org.id)}/applications/${item.id}/transitions`,
              { method: "POST", data: { status: target }, signal },
            ), async (result, owned) => {
              if (result.id !== item.id || result.organization_id !== org.id || result.job_id !== job.id)
                throw new Error("INVALID_SCOPE");
              ctx.candidates.clearResults();
              const refreshed = await pager.load();
              if (owned()) mutationNotice("Status updated", refreshed);
            }, save, true);
          });
          save.requiresWrite = true;
          save.canAct = () => item.allowed_statuses.includes(select.input.value);
          save.disabled = true;
          select.input.addEventListener("change", () => { save.disabled = !ctx.access.canWrite || !save.canAct(); });
          card.append(select.wrapper, save);
        } else card.append(node("p", "This application is in a terminal state.", "small muted"));
        content.append(card);
      }
      $("application-list").replaceChildren(content);
      if (!page.items.length) empty($("application-list"), "No applications match these filters.");
      $("applications-count").textContent = String(page.total);
      $("interviews-count").textContent = String(page.items.filter(item => item.status === "interview").length);
      $("offers-count").textContent = String(page.items.filter(item => item.status === "offer").length);
    },
  });
  $("application-create").addEventListener("click", async () => {
    const org = ctx.session.organization, job = ctx.session.job, candidate = ctx.session.candidate;
    if (!org || !job || !candidate) return;
    await ctx.perform("application-create", signal => ctx.api.request(`${orgPath(org.id)}/applications`, {
      method: "POST", signal, data: { job_id: job.id, candidate_id: candidate.id },
    }), async (value, owned) => {
      if (value.organization_id !== org.id || value.job_id !== job.id || value.candidate_id !== candidate.id)
        throw new Error("INVALID_SCOPE");
      ctx.candidates.clearResults();
      $("application-status-filter").value = "";
      $("application-filter").value = "";
      const refreshed = await pager.load({ reset: true });
      if (owned()) mutationNotice("Application created", refreshed);
    }, $("application-create"), true);
  });
  $("application-refresh").addEventListener("click", () => pager.load());
  return {
    load: () => pager.load(),
    reset() {
      pager.reset(); $("application-status-filter").value = "";
      for (const id of ["applications-count", "interviews-count", "offers-count"]) $(id).textContent = "—";
    },
  };
}
