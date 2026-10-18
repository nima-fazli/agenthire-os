import { $, node, empty } from "./dom.mjs";
import { orgPath, uuid } from "./session.mjs";
import { createPager, mutationNotice } from "./paging.mjs";

export function createWorkspace(ctx) {
  let organizations = [], jobs = [];

  function options(select, items, label, selected) {
    select.replaceChildren();
    const first = node("option", label); first.value = ""; select.append(first);
    const outside = selected && !items.some(item => item.id === selected.id);
    const values = outside ? [selected, ...items] : items;
    for (const item of values) {
      uuid(item.id);
      const option = node("option", (item.name ?? item.title) + (outside && item.id === selected.id ? " (انتخاب فعلی)" : ""));
      option.value = item.id; select.append(option);
    }
    select.value = selected?.id ?? "";
  }

  const organizationPage = createPager(ctx, {
    name: "organization", url: () => ctx.session.token ? "/organizations/page" : null,
    filters: () => ({ q: $("organization-filter").value.trim() }),
    clear: label => options($("organization-select"), [], label, ctx.session.organization),
    async render(page, preferred) {
      organizations = page.items;
      const selected = preferred ?? ctx.session.organization ?? organizations[0] ?? null;
      options($("organization-select"), organizations, "انتخاب سازمان", selected);
      if (!selected || selected.id !== ctx.session.organization?.id) return ctx.selectOrganization(selected);
    },
  });

  const jobPage = createPager(ctx, {
    name: "job", url: () => ctx.session.organization
      ? `${orgPath(ctx.session.organization.id)}/recruiting/jobs` : null,
    filters: () => ({ q: $("job-filter").value.trim(), status: $("job-status-filter").value }),
    clear: label => options($("job-select"), [], label, ctx.session.job),
    async render(page, preferred) {
      if (page.items.some(item => item.organization_id !== ctx.session.organization?.id)) throw new Error("INVALID_SCOPE");
      jobs = page.items;
      const selected = preferred ?? ctx.session.job ?? jobs[0] ?? null;
      options($("job-select"), jobs, "انتخاب شغل", selected);
      $("jobs-count").textContent = String(page.total);
      if (!selected || selected.id !== ctx.session.job?.id) return ctx.selectJob(selected);
    },
  });

  $("organization-select").addEventListener("change", () => {
    const id = $("organization-select").value;
    ctx.selectOrganization(organizations.find(item => item.id === id)
      ?? (ctx.session.organization?.id === id ? ctx.session.organization : null));
  });
  $("job-select").addEventListener("change", () => {
    const id = $("job-select").value;
    ctx.selectJob(jobs.find(item => item.id === id) ?? (ctx.session.job?.id === id ? ctx.session.job : null));
  });
  $("organization-form").addEventListener("submit", async event => {
    event.preventDefault();
    await ctx.perform("organization-create", signal => ctx.api.request("/organizations", {
      method: "POST", signal,
      data: { name: $("organization-name").value.trim(), slug: $("organization-slug").value.trim() },
    }), async created => {
      uuid(created.id);
      $("organization-form").reset(); $("organization-filter").value = "";
      const refreshed = await organizationPage.load({ reset: true, preferred: created });
      if (ctx.session.organization?.id === created.id) mutationNotice("سازمان ثبت شد", refreshed);
    }, $("organization-create"), true);
  });
  $("job-form").addEventListener("submit", async event => {
    event.preventDefault();
    const org = ctx.session.organization;
    if (!org) return;
    await ctx.perform("job-create", signal => ctx.api.request(`${orgPath(org.id)}/jobs`, {
      method: "POST", signal,
      data: { title: $("job-title").value.trim(), description: $("job-description").value.trim(), status: "draft" },
    }), async created => {
      if (created.organization_id !== org.id) throw new Error("INVALID_SCOPE");
      $("job-form").reset(); $("job-filter").value = $("job-status-filter").value = "";
      const refreshed = await jobPage.load({ reset: true, preferred: created });
      if (ctx.session.job?.id === created.id) mutationNotice("شغل ثبت شد", refreshed);
    }, $("job-create"), true);
  });

  async function loadOrganization() {
    if (!ctx.session.organization) return null;
    const results = await Promise.all([jobPage.load(), ctx.candidates.load()]);
    return results.every(value => value !== false);
  }
  $("workspace-refresh").addEventListener("click", loadOrganization);

  function showJob(job) {
    empty($("job-description-view"), "یک شغل بسازید یا انتخاب کنید.");
    if (job) {
      const title = node("h3", job.title), description = node("p", job.description, "job-description");
      title.dir = description.dir = "auto";
      $("job-description-view").replaceChildren(title, description);
    }
  }
  function clearOrganization() {
    jobs = []; jobPage.reset(); $("job-status-filter").value = "";
    options($("job-select"), [], "انتخاب شغل", null);
    $("organization-heading").textContent = ctx.session.organization?.name ?? "فضای کاری";
    $("jobs-count").textContent = $("candidates-count").textContent = "—";
    $("job-form").reset(); showJob(null);
  }
  return {
    loadOrganizations: () => organizationPage.load(), loadJobs: () => jobPage.load(), loadOrganization, clearOrganization, showJob,
    reset() { organizations = []; organizationPage.reset(); $("organization-form").reset(); clearOrganization(); },
  };
}
