// Page 5 — Système : état des services, journal des actions.
SX.pages.systeme = (() => {
  const { h, get, store, bus, clock } = SX;
  let el = {}, timers = [];
  const SERVICES = [
    ["api", "API", true], ["mqtt", "MQTT (broker)", true], ["db", "Base de données", true],
    ["vision", "Vision (YOLO)", false], ["analysis", "Analyse IA", false],
  ];

  async function pollHealth() {
    const hth = await get("/health");
    el.svc.replaceChildren();
    for (const [key, name, critical] of SERVICES) {
      const ok = hth?.[key] === true || hth?.[key] === "ok";
      const tr = h("tr", hth && !ok ? (critical ? "bad" : "warn") : "");
      const txt = !hth ? "indisponible" : ok ? "en service" : critical ? "HORS LIGNE" : "arrêté";
      tr.append(h("td", null, name), h("td", "val", txt));
      el.svc.append(tr);
    }
  }

  /** Résumé du boîtier en une ligne. */
  function device() {
    const s = store.state;
    if (!s) { el.dev.textContent = "Boîtier : état indisponible"; return; }
    const period = s.config?.interval_ms ? `, mesure toutes les ${s.config.interval_ms / 1000} s` : "";
    el.dev.textContent = `Boîtier ${s.device || "—"} (${s.simule ? "simulateur" : "boîtier réel"}) : ${s.online ? "en ligne" : "liaison perdue"}${period}`;
  }

  /** Détail lisible d'une action. */
  function describe(a) {
    const p = a.payload || {};
    const parts = [];
    if (a.kind === "ack") {
      parts.push(`alarme #${p.alert_id ?? "?"} acquittée`);
    } else if (a.kind === "login") {
      parts.push("connexion au dashboard");
    } else if (a.kind === "logout") {
      parts.push("déconnexion");
    } else if (a.kind === "login_echec") {
      parts.push(`mot de passe refusé pour « ${p.user ?? "?"} »`);
    } else {
      if ("buzzer" in p) parts.push(p.buzzer ? "buzzer en marche" : "buzzer à l'arrêt");
      if ("led" in p) parts.push(`voyant ${p.led}`);
      for (const [k, n] of Object.entries(SX.SENSOR_NAMES)) if (k in p) parts.push(`${n} ${p[k] ? "remis en service" : "mis hors service"}`);
      if ("interval_ms" in p) parts.push(`période de mesure réglée à ${p.interval_ms / 1000} s`);
    }
    return parts.length ? parts.join(", ") : JSON.stringify(p);
  }

  async function pollActions() {
    const list = await get("/actions?limit=100");
    const KIND = { command: "commande", config: "configuration", ack: "acquittement",
      login: "connexion", logout: "déconnexion", login_echec: "CONNEXION REFUSÉE" };
    el.actions.replaceChildren();
    (list || []).forEach((a) => el.actions.append(h("tr", null,
      h("td", "t", `${new Date(a.ts).toLocaleDateString("fr-FR")} ${clock(a.ts)}`), h("td", null, a.actor || "—"),
      h("td", null, KIND[a.kind] || a.kind), h("td", null, describe(a)))));
    if (!list || !list.length) {
      const td = h("td", null, list ? "Aucune action enregistrée." : "Journal indisponible.");
      td.colSpan = 4;
      el.actions.append(h("tr", "empty", td));
    }
  }

  function init(root) {
    el.svc = h("tbody");
    el.dev = h("p", "foot muted");
    el.actions = h("tbody");
    root.append(
      h("section", "panel narrow", h("h2", null, "Services"),
        h("table", "kv", h("thead", null, h("tr", null, h("th", null, "Service"), h("th", null, "État"))), el.svc), el.dev),
      h("section", "panel", h("h2", null, "Journal des actions"),
        h("div", "table-scroll tall", h("table", "alarms",
          h("thead", null, h("tr", null, ...["Heure", "Origine", "Type", "Détail"].map((t) => h("th", null, t)))),
          el.actions))));
    bus.on("state", device);
  }
  function show() {
    device(); pollHealth(); pollActions();
    timers = [setInterval(pollHealth, 5000), setInterval(pollActions, 10000)];
  }
  function hide() { timers.forEach(clearInterval); timers = []; }
  return { init, show, hide };
})();
