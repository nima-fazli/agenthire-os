import { $, node, empty, notice } from "./dom.mjs";
import { orgPath } from "./session.mjs";

export function createWorkspace(ctx) {
  let organizations = [], jobs = [];

  function options(select, items, label) {
    select.replaceChildren();

    const first = node("option", label);
    first.value = "";
    select.append(first);

    for (const item of items) {
      const option = node("option", item.name ?? item.title);
      option.value = item.id;
      select.append(option);
    }
  }

  $("organization-select").addEventListener("change", () => {
    ctx.selectOrganization(
      organizations.find(
        item => item.id === $("organization-select").value,
      ) ?? null,
    );
  });

  $("job-select").addEventListener("change", () => {
    ctx.selectJob(
      jobs.find(item => item.id === $("job-select").value) ?? null,
    );
  });

  $("organization-form").addEventListener("submit", async event => {
    event.preventDefault();

    await ctx.perform(
      "organization-create",
      signal => ctx.api.request("/organizations", {
        method: "POST",
        signal,
        data: {
          name: $("organization-name").value.trim(),
          slug: $("organization-slug").value.trim(),
        },
      }),
      async created => {
        $("organization-form").reset();
        const refreshed = await loadOrganizations(created.id);

        if (ctx.session.organization?.id === created.id) {
          notice(
            refreshed === false
              ? "سازمان ثبت شد؛ دریافت فهرست‌ها کامل نشد. آن‌ها را تازه‌سازی کنید."
              : "سازمان ثبت شد.",
            refreshed === false,
          );
        }
      },
      $("organization-create"),
      true,
    );
  });

  $("job-form").addEventListener("submit", async event => {
    event.preventDefault();

    if (!ctx.session.organization) return;

    await ctx.perform(
      "job-create",
      signal => ctx.api.request(
        `${orgPath(ctx.session.organization.id)}/jobs`,
        {
          method: "POST",
          signal,
          data: {
            title: $("job-title").value.trim(),
            description: $("job-description").value.trim(),
            status: "draft",
          },
        },
      ),
      async created => {
        $("job-form").reset();
        const refreshed = await loadOrganization(created.id);

        if (ctx.session.job?.id === created.id) {
          notice(
            refreshed === false
              ? "شغل ثبت شد؛ دریافت فهرست‌ها کامل نشد. آن‌ها را تازه‌سازی کنید."
              : "شغل ثبت شد.",
            refreshed === false,
          );
        }
      },
      $("job-create"),
      true,
    );
  });

  $("workspace-refresh").addEventListener("click", () => {
    loadOrganization(ctx.session.job?.id);
  });

  async function loadOrganizations(preferred = null) {
    return ctx.perform(
      "organizations",
      signal => ctx.api.request("/organizations", { signal }),
      async items => {
        organizations = items;

        options($("organization-select"), items, "انتخاب سازمان");

        const selected = items.find(
          item => item.id === (preferred ?? ctx.session.organization?.id),
        ) ?? items[0] ?? null;

        $("organization-select").value = selected?.id ?? "";
        await ctx.selectOrganization(selected);
      },
    );
  }

  async function loadOrganization(preferred = null) {
    const org = ctx.session.organization;
    const previousCandidate = ctx.session.candidate?.id;

    if (!org) return;

    return ctx.perform(
      "organization",
      signal => Promise.all([
        ctx.api.request(`${orgPath(org.id)}/jobs`, { signal }),
        ctx.api.request(`${orgPath(org.id)}/candidates`, { signal }),
      ]),
      async ([loadedJobs, candidates]) => {
        if (
          [...loadedJobs, ...candidates].some(
            item => item.organization_id !== org.id,
          )
        ) {
          throw new Error("INVALID_SCOPE");
        }

        jobs = loadedJobs;

        options($("job-select"), jobs, "انتخاب شغل");
        $("jobs-count").textContent = String(jobs.length);
        $("candidates-count").textContent = String(candidates.length);

        ctx.candidates.setItems(candidates);

        const selected = jobs.find(
          item => item.id === (preferred ?? ctx.session.job?.id),
        ) ?? jobs[0] ?? null;

        $("job-select").value = selected?.id ?? "";
        await ctx.selectJob(selected);

        if (
          ctx.session.organization?.id === org.id &&
          ctx.session.candidate?.id === previousCandidate
        ) {
          const current = candidates.find(
            item => item.id === previousCandidate,
          ) ?? null;

          await ctx.selectCandidate(current);
        }
      },
      $("workspace-refresh"),
    );
  }

  function clearOrganization() {
    jobs = [];

    options($("job-select"), [], "ابتدا سازمان را انتخاب کنید");

    $("organization-heading").textContent =
      ctx.session.organization?.name ?? "فضای کاری";

    $("jobs-count").textContent = $("candidates-count").textContent = "—";
    $("job-form").reset();
    $("job-create").disabled = !ctx.session.organization;
    $("workspace-refresh").disabled = !ctx.session.organization;

    empty(
      $("job-description-view"),
      "یک شغل انتخاب کنید تا معیارها و شواهد آن نمایش داده شود.",
    );
  }

  function showJob(job) {
    empty($("job-description-view"), "یک شغل بسازید یا انتخاب کنید.");

    if (job) {
      const title = node("h3", job.title);
      const description = node("p", job.description, "job-description");
      description.dir = "auto";
      $("job-description-view").replaceChildren(title, description);
    }
  }

  function reset() {
    organizations = [];
    options($("organization-select"), [], "انتخاب سازمان");
    $("organization-form").reset();
    clearOrganization();
  }

  return {
    loadOrganizations,
    loadOrganization,
    clearOrganization,
    showJob,
    reset,
  };
}
