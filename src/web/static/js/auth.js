// t_2ab8f3be: shared login/register behavior (inline scripts extracted).
// 1) Show the error the backend 303-redirects here as ?error=<msg>
//    (t_6f351b30 contract). textContent keeps it XSS-safe; focus moves to the
//    alert so screen readers announce it (tabindex="-1").
// 2) Password show/hide toggle.
const formError = new URLSearchParams(location.search).get("error");
if (formError) {
  const el = document.getElementById("form-error");
  el.textContent = formError;
  el.hidden = false;
  el.focus();
}

document.querySelectorAll(".pw-toggle").forEach((btn) => {
  btn.addEventListener("click", () => {
    const input = document.getElementById(btn.dataset.target);
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.textContent = show ? "Hide" : "Show";
    btn.setAttribute("aria-pressed", String(show));
    btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
  });
});
