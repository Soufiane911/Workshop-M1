// Page 1 — Vue d'ensemble : l'essentiel seulement, le détail est sur les autres pages.
SX.pages[""] = (() => {
  const { h, num, store, bus } = SX;
  const KPI = [
    { key: "temp", tag: "TT-01", name: "Température", unit: "°C", dec: 1 },
    { key: "hum", tag: "HT-01", name: "Humidité", unit: "%", dec: 1 },
    { key: "gaz", tag: "GT-01", name: "Gaz", unit: "brut", dec: 0 },
  ];
  const MAX_ALARMS = 20; // la liste défile si la fenêtre est trop basse
  const TREND = { hausse: "▲", baisse: "▼", stable: "=", inconnue: "?" };
  const kpis = {};      // key → éléments de la carte
  let el = {};
  let active = false;

  // ----- Cartes indicateurs : maintenant, prévu +10 min, tendance -----

  function kpiCard(k) {
    const val = (cls) => h("span", `kc-v ${cls}`, "—");
    const now = { v: val("now") }, fut = { v: val("fut") };
    const slope = h("p", "kpi-line", "—");
    // Seuil de danger : purement informatif, affiché pour la température seulement
    const thr = k.key === "temp" ? h("p", "kpi-line muted", " ") : null;
    const canvas = h("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", `Courbe ${k.name} sur 10 minutes avec prévision`);
    // Chiffres à gauche, courbe à droite : la carte reste basse et sans vide
    const nums = h("div", "kpi-nums",
      h("span", "kc-k", "maintenant"), h("span", "kc-k", "prévu +10 min"),
      now.v, fut.v, slope);
    if (thr) nums.append(thr);
    const card = h("section", "panel kpi",
      h("h2", null, `${k.tag} ${k.name}`, h("small", null, k.unit)),
      h("div", "kpi-body", nums, h("div", "spark", canvas)));
    kpis[k.key] = { now, fut, slope, thr, chart: SX.makeChart(canvas, { small: true }) };
    return card;
  }

  function renderKpi(k) {
    const o = kpis[k.key];
    const s = store.forecast?.series?.[k.key];
    const live = store.last ? store.last[k.key] : null;
    const nowV = live ?? s?.now;
    o.now.v.textContent = num(nowV, k.dec);
    o.fut.v.textContent = num(s?.forecast, k.dec);

    const sl = s?.slope_per_min;
    o.slope.textContent = sl === null || sl === undefined
      ? "tendance indisponible"
      : `${TREND[s.trend] || "?"} ${sl > 0 ? "+" : ""}${num(sl, 2)} ${k.unit}/min`;
    if (o.thr) {
      const m = s?.minutes_to_threshold;
      const known = m !== null && m !== undefined;
      const soon = known && m <= 10;
      o.thr.textContent = !s?.danger_threshold || s.forecast === null ? " "
        : known && m === 0 ? `seuil ${s.danger_threshold} ${k.unit} atteint`
        : known ? `seuil ${s.danger_threshold} ${k.unit} dans ~${Math.round(m)} min` : `seuil ${s.danger_threshold} ${k.unit} : pas d'approche`;
      o.thr.classList.toggle("warn-text", soon);
      o.thr.classList.toggle("muted", !soon);
    }
    drawSpark(k, o, s, nowV);
  }

  function drawSpark(k, o, s, nowV) {
    const limit = Date.now() - 10 * 60000;
    const past = store.measures.filter((m) => new Date(m.ts) >= limit && m[k.key] !== null)
      .map((m) => ({ x: new Date(m.ts).getTime(), y: m[k.key] }));
    const last = store.last ? new Date(store.last.ts) : new Date();
    o.chart.data.datasets[0].data = SX.breakGaps(SX.bucket(past, 120), 30000);
    o.chart.data.datasets[1].data = SX.forecastPath(s, last, nowV, store.forecast?.horizon_min || 10);
    o.chart.options.scales.x.min = last.getTime() - 10 * 60000;
    o.chart.options.scales.x.max = last.getTime() + 10 * 60000;
    o.chart.update("none");
  }

  // ----- Analyse IA -----

  const AN_STATE = { normal: "normal", derive: "DÉRIVE", anomalie: "ANOMALIE", inactif: "service arrêté" };

  function renderAnalysis() {
    const a = store.analysis;
    const c = el.analysis;
    c.box.classList.remove("bad", "warn");
    c.state.textContent = a ? AN_STATE[a.state] || a.state : "indisponible";
    c.expl.textContent = a && a.state !== "inactif" ? a.explanation || "" : "";
    if (a?.state === "anomalie") c.box.classList.add("bad");
    else if (a?.state === "derive") c.box.classList.add("warn");
  }

  // ----- Caméra, alarmes -----

  function setStream() {
    const on = store.visionActive && active;
    el.img.hidden = !on;
    el.empty.hidden = on;
    // Flux MJPEG ouvert seulement quand la page est affichée
    if (on) { if (!el.img.getAttribute("src")) el.img.src = `${SX.API}/vision/stream?t=${Date.now()}`; }
    else if (el.img.getAttribute("src")) el.img.removeAttribute("src");
  }

  function renderAlarms() {
    const list = SX.unacked();
    el.alarmBody.replaceChildren();
    list.slice(0, MAX_ALARMS).forEach((a) => el.alarmBody.append(SX.alarmRow(a, false, (t) => { el.alarmMsg.textContent = t; })));
    if (!list.length) {
      const td = h("td", null, "Aucune alarme active.");
      td.colSpan = 5;
      el.alarmBody.append(h("tr", "empty", td));
    }
    el.more.textContent = list.length > MAX_ALARMS ? `toutes les alarmes (${list.length - MAX_ALARMS} autres)` : "toutes les alarmes";
  }

  // ----- Construction -----

  function init(root) {
    el = {};
    const kpiRow = h("div", "ov-kpis");
    KPI.forEach((k) => kpiRow.append(kpiCard(k)));

    const an = { state: h("span", "an-state", "—"), expl: h("p", "an-expl") };
    an.box = h("section", "panel an", h("h2", null, "Analyse IA de l'environnement"),
      h("div", "an-body", an.state, an.expl));
    el.analysis = an;

    el.img = h("img");
    el.img.alt = "Flux de la webcam analysé par l'IA";
    el.img.hidden = true;
    el.empty = h("div", "video-empty", "Vision arrêtée : aucun flux.");
    const camLink = h("a", "link", "page Caméra");
    camLink.href = "#/camera";
    const camBox = h("section", "panel cam", h("h2", null, "Caméra"),
      h("div", "video-frame", el.img, el.empty), h("p", "foot", camLink));

    el.alarmBody = h("tbody");
    el.alarmMsg = h("span", "muted");
    el.alarmMsg.setAttribute("role", "status");
    el.more = h("a", "link", "toutes les alarmes");
    el.more.href = "#/alarmes";
    const alBox = h("section", "panel al", h("h2", null, "Alarmes non acquittées"),
      h("div", "table-scroll", h("table", "alarms", el.alarmBody)),
      h("p", "foot", el.alarmMsg, el.more));

    // Caméra à gauche sur toute la hauteur ; à droite : analyse IA, alarmes (extensible), commandes
    root.append(kpiRow,
      h("div", "ov-main", camBox, h("div", "ov-side", an.box, alBox, SX.commandsPanel())));

    bus.on("forecast", () => { if (active) KPI.forEach(renderKpi); });
    bus.on("measure", () => { if (active) KPI.forEach(renderKpi); });
    bus.on("analysis", renderAnalysis);
    bus.on("alerts", () => { if (active) renderAlarms(); });
    bus.on("vision", setStream);
  }

  function show() {
    active = true;
    KPI.forEach(renderKpi);
    renderAnalysis(); renderAlarms(); setStream();
    KPI.forEach((k) => kpis[k.key].chart.resize());
  }
  function hide() {
    active = false;
    setStream();
  }
  return { init, show, hide };
})();
