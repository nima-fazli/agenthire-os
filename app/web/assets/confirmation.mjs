import { $ } from "./dom.mjs";

export function createConfirmation() {
  const dialog = $("confirm-dialog"), input = $("confirm-input"), accept = $("confirm-accept");
  let pending = null, phrase = "", previousFocus = null;

  function cancel() {
    if (dialog.open) dialog.close("cancel");
    else finish(false);
  }
  function finish(accepted) {
    const resolve = pending;
    pending = null;
    input.value = "";
    if (previousFocus?.isConnected) previousFocus.focus();
    previousFocus = null;
    resolve?.(accepted);
  }
  input.addEventListener("input", () => { accept.disabled = Boolean(phrase && input.value !== phrase); });
  $("confirm-cancel").addEventListener("click", cancel);
  $("confirm-form").addEventListener("submit", event => {
    event.preventDefault();
    if (pending && (!phrase || input.value === phrase)) dialog.close("accept");
  });
  dialog.addEventListener("close", () => finish(dialog.returnValue === "accept"));
  dialog.addEventListener("cancel", event => { event.preventDefault(); cancel(); });

  return {
    cancel,
    ask({ title, message, requiredText = "" }) {
      if (pending) return Promise.resolve(false);
      phrase = requiredText;
      $("confirm-title").textContent = title;
      $("confirm-message").textContent = message;
      $("confirm-label").hidden = !phrase;
      input.value = "";
      input.required = Boolean(phrase);
      accept.disabled = Boolean(phrase);
      previousFocus = document.activeElement;
      return new Promise(resolve => {
        pending = resolve;
        dialog.returnValue = "";
        dialog.showModal();
        (phrase ? input : $("confirm-cancel")).focus();
      });
    },
  };
}
