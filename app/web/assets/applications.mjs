import { $, node, button, empty, field } from "./dom.mjs";
import { createPager, mutationNotice } from "./paging.mjs";
import { orgPath, uuid } from "./session.mjs";

export const applicationLabels = Object.freeze({
  applied: "ثبت درخواست", screening: "بررسی اولیه", interview: "مصاحبه",
  offer: "پیشنهاد همکاری", hired: "استخدام‌شده", rejected: "ردشده",
});

export function createApplications(ctx) {
  const pager = createPager(ctx, {
    name: "application",
    url: () => ctx.session.job ? `${orgPath(ctx.session.organization.id)}/recruiting/applications` : null,
    filters: () => ({ q: $("application-filter").value.trim(), status: $("application-status-filter").value,
      job_id: ctx.session.job.id }),
    clear: text => empty($("application-list"), text),
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
        card.append(title, node("p", `${item.job_title} · ${applicationLabels[item.status]}`, "small muted"));
        card.append(button("بازکردن پرونده", () => ctx.selectCandidateId(item.candidate_id)));
        if (item.allowed_statuses.length) {
          const select = field("وضعیت بعدی", { value: "",
            options: [["", "انتخاب وضعیت"], ...item.allowed_statuses.map(value => [value, applicationLabels[value]])] });
          const save = button("ثبت تغییر وضعیت", async () => {
            const target = select.input.value;
            if (!item.allowed_statuses.includes(target)) return;
            const accepted = await ctx.confirm.ask({ title: "تأیید تغییر وضعیت",
              message: `${item.candidate_name} · ${item.job_title}: ${applicationLabels[item.status]} ← ${applicationLabels[target]}` });
            if (!accepted || ctx.session.organization?.id !== org.id || ctx.session.job?.id !== job.id) return;
            await ctx.perform("application-transition", signal => ctx.api.request(
              `${orgPath(org.id)}/applications/${item.id}/transitions`,
              { method: "POST", data: { status: target }, signal },
            ), async (result, owned) => {
              if (result.id !== item.id || result.organization_id !== org.id || result.job_id !== job.id)
                throw new Error("INVALID_SCOPE");
              ctx.candidates.clearResults();
              const refreshed = await pager.load();
              if (owned()) mutationNotice("وضعیت ثبت شد", refreshed);
            }, save, true);
          });
          save.disabled = true;
          select.input.addEventListener("change", () => { save.disabled = !item.allowed_statuses.includes(select.input.value); });
          card.append(select.wrapper, save);
        } else card.append(node("p", "این درخواست در وضعیت نهایی است.", "small muted"));
        content.append(card);
      }
      $("application-list").replaceChildren(content);
      if (!page.items.length) empty($("application-list"), "درخواستی مطابق این فیلتر وجود ندارد.");
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
      if (owned()) mutationNotice("درخواست استخدام ثبت شد", refreshed);
    }, $("application-create"), true);
  });
  $("application-refresh").addEventListener("click", () => pager.load());
  return {
    load: () => pager.load(),
    reset() { pager.reset(); $("application-status-filter").value = ""; },
  };
}
