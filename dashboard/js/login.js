// Sentinel-X — page de connexion : envoie l'identifiant à l'API, qui pose un cookie de session.
(() => {
  const form = document.getElementById("login-form");
  const err = document.getElementById("login-error");
  const btn = document.getElementById("login-btn");

  const show = (text) => { err.textContent = text; err.hidden = !text; };

  // Déjà connecté : directement au dashboard
  fetch("/api/v1/auth/me").then((r) => { if (r.ok) location.replace("/"); }).catch(() => {});

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const username = form.username.value.trim();
    const password = form.password.value;
    if (!username || !password) { show("Renseigner l'identifiant et le mot de passe."); return; }
    btn.disabled = true;
    show("");
    try {
      const r = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (r.ok) { location.replace("/"); return; }
      const body = await r.json().catch(() => ({}));
      show(typeof body.detail === "string" ? body.detail : `Erreur ${r.status}`);
      form.password.value = "";
      form.password.focus();
    } catch {
      show("API injoignable.");
    } finally {
      btn.disabled = false;
    }
  });
})();
