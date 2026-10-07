// Page 2 — Capteurs : une fiche courte par capteur (le détail est replié) + les actionneurs.
SX.pages.capteurs = (() => {
  const { h, num, rel, store, bus, get, post } = SX;
  const HEALTH = { ok: "ok", degrade: "dégradé", panne: "panne", hors_service: "hors service" };
  const QTY = { temp: ["Température", "°C"], hum: ["Humidité", "%"], gaz: ["Gaz (brut)", ""] };
  const SHEETS = [
    { id: "dht22", title: "DHT22 — température et humidité", img: "dht22", charts: ["temp", "hum"] },
    { id: "mq2", title: "MQ-2 — gaz et fumée", img: "mq2", charts: ["gaz"] },
    { id: "pir", title: "PIR — présence", img: "pir", charts: ["presence"] },
  ];
  const sheets = {}; // id → { rows, value, health, statsBody, toggleInput, charts }
  let data = null, metrics = null, timers = [], act = {}, msg, visible = false;

  const photo = (name, label) => {
    const img = h("img");
    img.src = `img/${name}.png`;
    img.alt = label;
    img.loading = "lazy";
    // Photo absente : repère neutre à la place
    img.addEventListener("error", () => img.replaceWith(h("div", "ph", "photo à venir")), { once: true });
    return h("div", "photo", img);
  };

  const kvRow = (label, valueEl) => h("tr", null, h("th", null, label), valueEl);

  function sheet(def) {
    const rows = {};
    const cell = (k) => (rows[k] = h("td", "val", "—"));
    // Détail technique, replié par défaut
    const body = h("tbody");
    body.append(kvRow("Branchement", cell("wiring")), kvRow("Période de mesure", cell("period")),
      kvRow("Dernière lecture", cell("last")), kvRow("Lectures ratées (3 min)", cell("failed")),
      kvRow("Valeur bloquée", cell("stuck")), kvRow("Hors plage", cell("range")));
    if (def.id === "mq2") body.append(kvRow("Préchauffage", cell("preheat")));
    if (def.id === "pir") body.append(kvRow("Détections (1 h)", cell("det")), kvRow("Dernière détection", cell("lastdet")));
    const statsBody = def.id === "pir" ? null : h("tbody");
    const details = h("details", "more", h("summary", null, "Détails"), h("table", "kv", body),
      statsBody ? h("table", "stats",
        h("thead", null, h("tr", null, ...["Sur 1 h", "min", "moy", "max"].map((t, i) => h("th", i ? "num" : null, t)))),
        statsBody) : null);

    const toggleInput = h("input");
    toggleInput.type = "checkbox";
    toggleInput.addEventListener("change", async () => {
      const on = toggleInput.checked;
      const r = await post("/config", { [def.id]: on });
      say(r.ok ? `${SX.SENSOR_NAMES[def.id]} ${on ? "remis en service" : "mis hors service"}` : `Ordre non transmis : ${r.error}`);
      poll();
    });

    const value = h("td", "val big", "—");
    const health = h("td", "val", "—");
    const top = h("table", "kv", h("tbody", null,
      kvRow("Valeur", value), kvRow("Santé", health),
      kvRow("Service", h("td", null, h("label", "check", toggleInput, " en service")))));

    const charts = def.charts.map((q) => {
      const canvas = h("canvas");
      const name = q === "presence" ? "Présence (1 h)" : `${QTY[q][0]}${QTY[q][1] ? ` (${QTY[q][1]})` : ""}, 1 h + prévision`;
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", `Courbe ${name}`);
      const chart = SX.makeChart(canvas, { step: q === "presence", yTicks: q === "presence" ? (v) => (v === 1 ? "oui" : v === 0 ? "non" : "") : undefined });
      if (q === "presence") { chart.options.scales.y.min = 0; chart.options.scales.y.max = 1; chart.options.scales.y.grace = 0; }
      return { q, chart, box: h("div", "chart-sheet", h("span", "trend-k", name), h("div", "chart-box", canvas)) };
    });

    sheets[def.id] = { rows, value, health, statsBody, toggleInput, charts };
    return h("section", "panel sheet",
      h("h2", null, def.title),
      h("div", "sheet-top", photo(def.img, def.title), top),
      ...charts.map((c) => c.box),
      details);
  }

  function actuators() {
    const item = (name, label, key) => {
      act[key] = h("span", "val", "—");
      return h("div", "act", photo(name, label), h("div", null, h("b", null, label), act[key]));
    };
    msg = h("p", "hint");
    msg.setAttribute("role", "status");
    return h("section", "panel sheet",
      h("h2", null, "Actionneurs et périphériques"),
      h("div", "acts", item("oled", "Écran OLED", "oled"), item("buzzer", "Buzzer", "buzzer"), item("led", "Voyant", "led"),
        item("esp8266", "Carte ESP8266", "esp"), item("webcam", "Webcam", "cam")),
      msg);
  }

  function say(t) { if (msg) msg.textContent = `${SX.clock(new Date())} · ${t}`; }

  /** Valeur courante lue dans la dernière mesure reçue (temps réel). */
  function fillValue(id) {
    const m = store.last;
    const v = sheets[id].value;
    if (!m) { v.textContent = "—"; return; }
    if (id === "dht22") v.textContent = m.temp === null ? "—" : `${num(m.temp, 1)} °C · ${num(m.hum, 1)} %`;
    else if (id === "mq2") v.textContent = m.gaz === null ? "—" : num(m.gaz, 0);
    else v.textContent = m.presence === null ? "—" : m.presence ? "DÉTECTÉE" : "aucune";
    v.classList.toggle("bad-text", id === "pir" && m.presence === true);
  }

  function fillSheet(id) {
    const s = sheets[id];
    const d = data?.sensors?.[id];
    const r = s.rows;
    fillValue(id);
    if (!d) {
      s.health.textContent = "indisponible";
      Object.values(r).forEach((c) => { c.textContent = "—"; });
      return;
    }
    s.health.textContent = HEALTH[d.health] || "—";
    s.health.className = `val ${d.health === "ok" ? "" : d.health === "degrade" ? "warn-text" : "bad-text"}`;
    s.toggleInput.checked = d.enabled !== false;
    r.wiring.textContent = `${d.pin || "—"} · ${d.supply || "—"}`;
    r.period.textContent = d.interval_ms ? `${d.interval_ms / 1000} s` : "—";
    r.last.textContent = rel(d.last_read);
    r.failed.textContent = d.failed_reads ?? "—";
    r.stuck.textContent = d.stuck ? "oui" : "non";
    r.range.textContent = d.out_of_range ? "oui" : "non";
    if (r.preheat) r.preheat.textContent = d.preheat_done ? "terminé" : "en cours";
    if (r.det) { r.det.textContent = d.detections_1h ?? "—"; r.lastdet.textContent = rel(d.last_detection); }

    if (!s.statsBody) return;
    s.statsBody.replaceChildren();
    for (const [q, st] of Object.entries(d.stats || {})) {
      const [name, unit] = QTY[q] || [q, ""];
      const dec = q === "gaz" ? 0 : 1;
      s.statsBody.append(h("tr", null, h("td", null, `${name}${unit ? ` (${unit})` : ""}`),
        h("td", "num", num(st.min, dec)), h("td", "num", num(st.avg, dec)), h("td", "num", num(st.max, dec))));
    }
  }

  function fillActuators() {
    const a = data?.sensors?.actuators;
    const s = store.state;
    const buz = a ? a.buzzer : s?.buzzer;
    const led = a ? a.led : s?.led;
    act.oled.textContent = a?.oled ?? "—";
    act.buzzer.textContent = buz === undefined || buz === null ? "—" : buz ? "en marche" : "à l'arrêt";
    act.led.textContent = led ?? "—";
    act.esp.textContent = s ? (s.online ? "en ligne" : "liaison perdue") : "—";
    act.cam.textContent = store.visionActive ? "analysée par l'IA" : "analyse arrêtée";
  }

  async function pollMetrics() {
    metrics = await get("/metrics?minutes=60");
    drawCharts();
  }

  function drawCharts() {
    if (!metrics || !visible) return;
    const f = store.forecast;
    const last = metrics.length ? new Date(metrics[metrics.length - 1].ts) : new Date();
    for (const s of Object.values(sheets)) {
      for (const c of s.charts) {
        const pts = metrics.map((m) => ({ x: new Date(m.ts).getTime(), y: c.q === "presence" ? (m.presence ? 1 : 0) : m[c.q] }));
        const lastV = pts.length ? pts[pts.length - 1].y : null;
        c.chart.data.datasets[0].data = SX.breakGaps(SX.bucket(pts, 200, c.q === "presence"));
        c.chart.data.datasets[1].data = c.q === "presence" ? [] : SX.forecastPath(f?.series?.[c.q], last, lastV, f?.horizon_min || 10);
        c.chart.options.scales.x.min = last.getTime() - 60 * 60000;
        c.chart.options.scales.x.max = last.getTime() + 10 * 60000;
        c.chart.update("none");
      }
    }
  }

  async function poll() {
    data = await get("/sensors");
    SHEETS.forEach((d) => fillSheet(d.id));
    fillActuators();
  }

  function init(root) {
    const grid = h("div", "grid-sheets");
    SHEETS.forEach((d) => grid.append(sheet(d)));
    grid.append(actuators());
    root.append(grid);
    bus.on("measure", () => { if (visible) SHEETS.forEach((d) => fillValue(d.id)); });
    bus.on("state", () => { if (visible) fillActuators(); });
    bus.on("forecast", drawCharts);
    bus.on("vision", () => { if (visible) fillActuators(); });
  }
  function show() {
    visible = true;
    poll(); pollMetrics();
    Object.values(sheets).forEach((s) => s.charts.forEach((c) => c.chart.resize()));
    timers = [setInterval(poll, 5000), setInterval(pollMetrics, 30000)];
  }
  function hide() { visible = false; timers.forEach(clearInterval); timers = []; }
  return { init, show, hide };
})();
