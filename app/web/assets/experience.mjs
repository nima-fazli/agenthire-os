// Browser-only presentation: the existing modules still own data and mutations.
export function createExperience(doc, host = window) {
  const find = id => doc.getElementById(id);
  const shell = find("shell");
  const context = find("context-dialog");
  const links = [...doc.querySelectorAll("[data-workspace-view]")];
  const tabs = [...doc.querySelectorAll("[data-dossier-tab]")];
  const descriptions = {
    review: ["Candidates", "A closer look at the people behind every application."],
    applications: ["Applications", "Keep every application moving, with the full context."],
    setup: ["Jobs", "Define the role. Make space for the right people."],
    access: ["Your team", "Great hiring is a team effort. Keep access in the right hands."],
    account: ["Settings", "A little housekeeping for a secure workspace."],
  };
  let selectedId = null;
  let contextTrigger = null;

  function selectTab(name, focus = false) {
    for (const tab of tabs) {
      const selected = tab.dataset.dossierTab === name;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      find(`dossier-${tab.dataset.dossierTab}`).hidden = !selected;
      if (selected && focus) tab.focus();
    }
  }
  for (const tab of tabs) {
    tab.addEventListener("click", () => selectTab(tab.dataset.dossierTab));
    tab.addEventListener("keydown", event => {
      const current = tabs.indexOf(tab);
      let index;
      if (event.key === "ArrowRight") index = (current + 1) % tabs.length;
      else if (event.key === "ArrowLeft") index = (current + tabs.length - 1) % tabs.length;
      else if (event.key === "Home") index = 0;
      else if (event.key === "End") index = tabs.length - 1;
      else return;
      event.preventDefault();
      selectTab(tabs[index].dataset.dossierTab, true);
    });
  }

  function syncSelection() {
    const id = find("candidate-heading").dataset.candidateId ?? null;
    if (id !== selectedId) {
      selectedId = id;
      selectTab("overview");
      if (id && host.matchMedia("(max-width: 760px)").matches) {
        const panel = find("candidate-panel");
        panel.focus({ preventScroll: true });
        panel.scrollIntoView({ block: "start", behavior:
          host.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      }
    }
    find("candidate-panel").classList.toggle("has-candidate", Boolean(id));
    for (const row of doc.querySelectorAll(".candidate-card")) {
      const selected = Boolean(id && row.dataset.candidateId === id);
      row.classList.toggle("is-selected", selected);
      row.querySelector("button")?.setAttribute("aria-pressed", String(selected));
    }
  }

  function syncChrome() {
    const signedIn = !shell.hidden;
    find("primary-navigation").hidden = find("workspace-tools").hidden = !signedIn;
    doc.body.classList.toggle("signed-in", signedIn);
    const active = links.find(link => link.getAttribute("aria-current") === "page");
    const view = active?.dataset.workspaceView ?? "review";
    const dossierParent = view === "applications" ? find("application-dossier-slot") : find("review-layout");
    const dossier = find("candidate-panel");
    if (dossier.parentElement !== dossierParent) dossierParent.append(dossier);
    const [title, description] = descriptions[view];
    if (find("workspace-page-title").textContent !== title) find("workspace-page-title").textContent = title;
    if (find("workspace-page-description").textContent !== description) find("workspace-page-description").textContent = description;
    const org = find("organization-heading").textContent;
    const contextLabel = signedIn && org && org !== "Workspace" ? org : "Choose workspace";
    if (find("context-button-label").textContent !== contextLabel) find("context-button-label").textContent = contextLabel;
    const email = find("account-email").textContent;
    find("account-avatar").textContent = email ? email.slice(0, 2).toUpperCase() : "A";
    if (!signedIn) {
      if (context.open) context.close();
      for (const id of ["notification-center", "account-menu"]) {
        if (find(id).matches(":popover-open")) find(id).hidePopover();
      }
      find("auth-password").type = "password";
      find("password-reveal").setAttribute("aria-pressed", "false");
      find("password-reveal").setAttribute("aria-label", "Show password");
    }
  }

  find("context-open").addEventListener("click", () => {
    contextTrigger = doc.activeElement;
    if (!context.open) context.showModal();
    find("context-switcher").open = true;
    const org = find("organization-select");
    (org.matches(":disabled") ? find("context-close") : org).focus();
  });
  find("context-close").addEventListener("click", () => context.close());
  context.addEventListener("close", () => {
    if (contextTrigger?.isConnected && !shell.hidden) contextTrigger.focus();
    contextTrigger = null;
  });
  context.addEventListener("click", event => {
    if (event.target !== context) return;
    const rect = context.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) context.close();
  });
  find("password-reveal").addEventListener("click", () => {
    const password = find("auth-password");
    const show = password.type === "password";
    password.type = show ? "text" : "password";
    find("password-reveal").setAttribute("aria-pressed", String(show));
    find("password-reveal").setAttribute("aria-label", show ? "Hide password" : "Show password");
  });
  find("notification-center").addEventListener("toggle", event => {
    find("notification-toggle").setAttribute("aria-expanded", String(event.newState === "open"));
  });
  const chromeObserver = new host.MutationObserver(syncChrome);
  chromeObserver.observe(shell, { attributes: true, attributeFilter: ["hidden"] });
  chromeObserver.observe(find("primary-navigation"), { subtree: true, attributes: true, attributeFilter: ["aria-current"] });
  for (const id of ["organization-heading", "account-email"])
    chromeObserver.observe(find(id), { childList: true, subtree: true });
  const candidateObserver = new host.MutationObserver(syncSelection);
  candidateObserver.observe(find("candidate-heading"), { childList: true, attributes: true, attributeFilter: ["data-candidate-id"] });
  candidateObserver.observe(find("candidate-list"), { childList: true });
  syncChrome();
  syncSelection();
  return { destroy() { chromeObserver.disconnect(); candidateObserver.disconnect(); } };
}
