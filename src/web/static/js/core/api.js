// js/core/api.js — port of api-fetch.js (t_2ab8f3be contract).
// A 401 shows a dismissible "session expired" banner with a login link —
// never a silent redirect that discards in-progress work.
let bannerShown = false;

export async function apiFetch(input, init) {
  const response = await fetch(input, init);
  if (response.status === 401) showBanner();
  return response;
}

function showBanner() {
  if (bannerShown) return;
  bannerShown = true;
  const banner = document.createElement("div");
  banner.className = "session-banner";
  banner.setAttribute("role", "status");
  const text = document.createElement("span");
  text.textContent = "Session expired — your work is still here.";
  const link = document.createElement("a");
  link.href = "login";
  link.textContent = "Log in again";
  const close = document.createElement("button");
  close.type = "button";
  close.setAttribute("aria-label", "Dismiss");
  close.textContent = "\u00d7";
  close.addEventListener("click", () => banner.remove());
  banner.append(text, link, close);
  document.body.prepend(banner);
}
