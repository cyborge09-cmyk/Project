/* Sign in / create account. */
(function () {
  "use strict";
  const { api } = window.CB;
  const form = document.getElementById("auth-form");
  const error = document.getElementById("auth-error");
  const submit = form.querySelector('button[type="submit"]');
  let mode = "login";

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      mode = tab.dataset.mode;
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t === tab));
      document.querySelectorAll('[data-only="signup"]').forEach((el) => { el.hidden = mode !== "signup"; });
      submit.textContent = mode === "signup" ? "Create account" : "Sign in";
      form.password.autocomplete = mode === "signup" ? "new-password" : "current-password";
      error.hidden = true;
    });
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    if (mode === "signup" && form.password.value.length < 8) {
      error.textContent = "Password must be at least 8 characters.";
      error.hidden = false;
      return;
    }
    submit.disabled = true;
    try {
      const payload = { email: form.email.value.trim(), password: form.password.value };
      if (mode === "signup") payload.full_name = form.full_name.value.trim() || null;
      const result = await api(mode === "signup" ? "/api/auth/signup" : "/api/auth/login", {
        method: "POST",
        body: payload,
      });
      if (result && result.confirmation_required) {
        error.textContent = result.message;
        error.hidden = false;
      } else {
        window.location.href = form.next.value || "/";
      }
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });
})();
