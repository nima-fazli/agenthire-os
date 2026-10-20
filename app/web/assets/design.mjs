const VIEWS = Object.freeze({
  review: { label: "Candidate review", target: "candidates-panel" },
  setup: { label: "Job setup", target: "profiles-panel" },
  applications: { label: "Applications", target: "applications-panel" },
  access: { label: "Members and access", target: "access-panel" },
  account: { label: "Account security", target: "account-panel" },
});

export function viewForTarget(target) {
  return Object.entries(VIEWS).find(([, value]) => value.target === target)?.[0] ?? null;
}

export function createDesign(doc, host = window) {
  const find = id => doc.getElementById(id);
  const shell = find("shell"), switcher = find("context-switcher"), help = find("help-dialog");
  const links = [...doc.querySelectorAll("[data-workspace-view]")];
  const panels = [...doc.querySelectorAll("[data-view-panel]")];
  const media = host.matchMedia("(max-width: 760px)");
  let active = "review", wasSignedIn = !shell.hidden, previousFocus = null;

  function show(view, focus = false) {
    if (!Object.hasOwn(VIEWS, view)) return false;
    active = view;
    for (const panel of panels) panel.hidden = panel.dataset.viewPanel !== view;
    for (const link of links) {
      if (link.dataset.workspaceView === view) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    find("workspace-view-label").textContent = VIEWS[view].label.toUpperCase();
    if (focus && !shell.hidden) find(VIEWS[view].target).focus();
    return true;
  }

  function refresh() {
    const signedIn = !shell.hidden;
    if (signedIn !== wasSignedIn) {
      wasSignedIn = signedIn;
      show("review");
      switcher.open = !media.matches;
      if (help.open) help.close();
      if (signedIn) find("candidates-panel").focus();
      else if (shell.contains(doc.activeElement)) find("auth-email").focus();
    }
    const org = find("organization-select"), job = find("job-select");
    const hasOrganization = signedIn && Boolean(org.value);
    const text = !hasOrganization ? "Choose an organization and job to begin."
      : job.value ? `Working on: ${job.selectedOptions[0]?.textContent ?? "Selected job"}`
        : "Organization selected. Choose or create a job to review its criteria and applications.";
    const context = find("selection-context");
    if (context.textContent !== text) context.textContent = text;
    find("workspace-start").hidden = hasOrganization || !signedIn;
  }

  for (const link of links) link.addEventListener("click", event => {
    event.preventDefault();
    show(link.dataset.workspaceView, true);
  });
  find("context-open").addEventListener("click", () => {
    switcher.open = true;
    const target = find("organization-select");
    (target.disabled ? switcher.querySelector("summary") : target).focus();
  });
  find("workspace-help").addEventListener("click", () => {
    if (help.open) return;
    previousFocus = doc.activeElement;
    help.showModal();
    find("help-close").focus();
  });
  help.addEventListener("close", () => {
    if (previousFocus?.isConnected && !previousFocus.closest("[hidden]")) previousFocus.focus();
    previousFocus = null;
  });
  const breakpoint = () => { switcher.open = !media.matches; };
  media.addEventListener("change", breakpoint);
  const candidateObserver = new host.MutationObserver(() => {
    if (active === "applications" && !shell.hidden && find("candidate-heading").querySelector("h3")) {
      show("review");
      find("candidate-panel").focus();
    }
  });
  candidateObserver.observe(find("candidate-heading"), { childList: true, subtree: true });
  const observer = new host.MutationObserver(refresh);
  observer.observe(shell, { attributes: true, attributeFilter: ["hidden"] });
  for (const id of ["organization-heading", "organization-select", "job-select", "job-description-view"])
    observer.observe(find(id), { childList: true, subtree: true });
  find("organization-select").addEventListener("change", refresh);
  find("job-select").addEventListener("change", refresh);
  show(active);
  breakpoint();
  refresh();
  return { show, refresh, destroy() { observer.disconnect(); candidateObserver.disconnect(); media.removeEventListener("change", breakpoint); } };
}

if (typeof document !== "undefined") createDesign(document);
