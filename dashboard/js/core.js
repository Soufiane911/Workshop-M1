// Sentinel-X — socle commun : API, WebSocket partagé, état global, bandeau d'état.
// Les pages (js/pages/*.js) s'appuient sur l'objet global SX.
const SX = (() => {
  const API = "/api/v1";
  const $ = (id) => document.getElementById(id);

  // ---------- Utilitaires DOM (texte toujours inséré via textContent) ----------

  /** Crée un élément : h("td", "num", "texte", autreNoeud). */
  function h(tag, cls, ...kids) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    for (const k of kids) if (k !== null && k !== undefined) e.append(k);
    return e;
  }

  const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString("fr-FR") : "—");
  const num = (v, d = 1) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d));

  /** Durée écoulée lisible : « il y a 12 s », « il y a 5 min ». */
  function rel(iso) {
    if (!iso) return "jamais";
    const s = Math.max(0, Math.round((Date.now() - new Date(iso)) / 1000));
    if (s < 90) return `il y a ${s} s`;
    if (s < 5400) return `il y a ${Math.round(s / 60)} min`;
    return `il y a ${Math.round(s / 3600)} h`;
  }

  // ---------- Bus d'évènements minimal ----------

  const handlers = {};
  const bus = {
    on(type, fn) { (handlers[type] ||= []).push(fn); },
    emit(type, data) { (handlers[type] || []).forEach((fn) => { try { fn(data); } catch (e) { console.error(e); } }); },
  };

  // ---------- Appels API (jamais d'exception : null / {ok:false} en cas d'échec) ----------

  /** Session expirée ou absente : retour à la page de connexion. */
  function toLogin(r) {
    if (r.status === 401) location.replace("/login.html");
    return r;
  }

  async function get(path) {
    try {
      const r = toLogin(await fetch(`${API}${path}`));
      return r.ok ? await r.json() : null;
    } catch {
      return null;
    }
  }

  async function post(path, body) {
    try {
      const r = toLogin(await fetch(`${API}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      }));
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        return { ok: false, error: typeof err.detail === "string" ? err.detail : `erreur ${r.status}` };
      }
      return { ok: true };
    } catch (e) {
      return { ok: false, error: "API injoignable" };
    }
  }

  // ---------- État partagé ----------

  const store = {
    state: null,      // dernier état du boîtier (/status, WS "state")
    last: null,       // dernière mesure
    measures: [],     // mesures des 10 dernières minutes
    alerts: new Map(),// id → alarme (200 dernières)
    analysis: null,   // dernière analyse IA
    forecast: null,   // dernière prévision
    visionActive: false,
    wsOn: false,
  };
  const MAX_MEASURES = 700;

  function unacked() {
    return [...store.alerts.values()].filter((a) => !a.acknowledged).sort((a, b) => b.id - a.id);
  }

  // ---------- Bandeau d'état ----------

  function refreshLast() {
    if (!store.last) return;
    const s = Math.max(0, Math.round((Date.now() - new Date(store.last.ts)) / 1000));
    $("v-last").textContent = `il y a ${s} s`;
    $("cell-last").classList.toggle("warn", s > 10);
  }

  function refreshAlarmCell() {
    const list = unacked();
    $("alerts-count").textContent = list.length;
    const latest = list[0];
    $("alarm-banner").textContent = latest ? `${clock(latest.ts)} · ${latest.message}` : "Aucune alarme active";
    const critical = list.some((a) => a.level === "critical");
    $("cell-alarm").classList.toggle("bad", critical);
    $("cell-alarm").classList.toggle("warn", !critical && list.length > 0);
  }

  function showState(s) {
    store.state = s;
    $("device-id").textContent = s.device || "—";
    $("device-label").textContent = (s.online ? "EN LIGNE" : "PERDUE") + (s.simule ? " (simulé)" : "");
    $("cell-device").classList.toggle("bad", !s.online);
    if (s.last_measure && !store.last) showMeasure(s.last_measure);
    bus.emit("state", s);
  }

  function showMeasure(m) {
    store.last = m;
    store.measures.push(m);
    if (store.measures.length > MAX_MEASURES) store.measures.shift();
    refreshLast();
    bus.emit("measure", m);
  }

  function setWs(on) {
    store.wsOn = on;
    $("ws-label").textContent = on ? "connecté" : "COUPÉ, reconnexion…";
    $("cell-ws").classList.toggle("bad", !on);
    bus.emit("ws", on);
  }

  function setVision(active) {
    store.visionActive = active;
    $("vision-label").textContent = active ? "en marche" : "arrêtée";
    bus.emit("vision", active);
  }

  async function checkVision() {
    const r = await get("/vision/status");
    if (r && r.active !== store.visionActive) setVision(!!r.active);
  }

  // ---------- Alarmes ----------

  function putAlert(a) {
    store.alerts.set(a.id, a);
    if (store.alerts.size > 200) store.alerts.delete(Math.min(...store.alerts.keys()));
    refreshAlarmCell();
    bus.emit("alerts", a);
  }

  function ackAlert(d) {
    const a = store.alerts.get(d.id);
    if (a) Object.assign(a, { acknowledged: true, acked_at: d.acked_at, acked_by: d.acked_by });
    refreshAlarmCell();
    bus.emit("alerts", a);
  }

  async function ack(id) {
    const r = await post(`/alerts/${id}/ack`);
    return r;
  }

  const PRIORITY = { critical: "critique", warning: "haute", info: "info" };

  /** Ligne de tableau d'alarme. full=true : colonnes Capture + Acquittement détaillé. */
  function alarmRow(a, full, onMsg) {
    const tr = h("tr", `${a.level} ${a.acknowledged ? "acked" : "unack"}`);
    tr.dataset.id = a.id;
    tr.append(h("td", "t", clock(a.ts)), h("td", null, h("span", `prio ${a.level}`, PRIORITY[a.level] || a.level)));
    tr.append(h("td", null, a.source), h("td", "msg", a.message));
    if (full) {
      const cap = h("td");
      if (a.snapshot) cap.append(snapButton(a.snapshot));
      tr.append(cap);
    }
    const ackTd = h("td");
    if (a.acknowledged) {
      ackTd.textContent = full ? `acquittée ${clock(a.acked_at)} par ${a.acked_by || "—"}` : "oui";
    } else {
      const b = h("button", "btn", "Acquitter");
      b.addEventListener("click", async () => {
        const r = await ack(a.id);
        if (!r.ok && onMsg) onMsg(`Acquittement refusé : ${r.error}`);
      });
      ackTd.append(b);
    }
    tr.append(ackTd);
    return tr;
  }

  function snapButton(url, label = "voir") {
    const b = h("button", "link", label);
    b.addEventListener("click", () => openSnap(url));
    return b;
  }

  function openSnap(url) {
    $("snap-img").src = url;
    $("snap-dialog").showModal();
  }

  // ---------- Commandes (partagées entre « Vue d'ensemble » et « Capteurs ») ----------

  const SENSOR_NAMES = { dht22: "DHT22", mq2: "MQ-2", pir: "PIR" };

  /** Tableau de commandes buzzer / voyant ; renvoie le panneau complet. */
  function commandsPanel() {
    const msg = h("p", "hint");
    msg.setAttribute("role", "status");
    const say = (t) => { msg.textContent = t ? `${clock(new Date())} · ${t}` : ""; };
    const send = async (body, ok) => {
      const r = await post("/commands", body);
      say(r.ok ? `ordre envoyé : ${ok}` : `Ordre non transmis : ${r.error}`);
    };
    const btn = (text, cls, body, ok) => {
      const b = h("button", `btn ${cls}`, text);
      b.addEventListener("click", () => send(body, ok));
      return b;
    };
    const sBuz = h("td", "state", "—");
    const sLed = h("td", "state", "—");
    const table = h("table", "controls");
    const tb = h("tbody");
    tb.append(
      h("tr", null, h("th", null, "Buzzer"),
        h("td", "btns", btn("Marche", "btn-alarm", { buzzer: true }, "buzzer en marche"), btn("Arrêt", "", { buzzer: false }, "buzzer à l'arrêt")), sBuz),
      h("tr", null, h("th", null, "Voyant"),
        h("td", "btns", btn("Vert", "", { led: "vert" }, "voyant vert"), btn("Rouge", "btn-alarm", { led: "rouge" }, "voyant rouge")), sLed),
    );
    table.append(tb);
    const panel = h("section", "panel", h("h2", null, "Commandes"), table, msg);
    const upd = (s) => {
      sBuz.textContent = s.buzzer ? "MARCHE" : "arrêt";
      sBuz.classList.toggle("on", !!s.buzzer);
      sLed.textContent = s.led === "rouge" ? "ROUGE" : "vert";
      sLed.classList.toggle("on", s.led === "rouge");
    };
    bus.on("state", upd);
    if (store.state) upd(store.state);
    return panel;
  }

  // ---------- Graphiques ----------

  /** Axe temps (ms epoch) : étiquettes HH:MM. */
  const hhmm = (v) => new Date(v).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

  /** Points de prévision à tracer après la dernière mesure : [{x, y}]. */
  function forecastPath(serie, fromTs, fromVal, horizonMin) {
    if (!serie || serie.forecast === null || serie.forecast === undefined || fromVal === null || fromVal === undefined) return [];
    const pts = (serie.points || []).filter((p) => p.value !== null && new Date(p.ts) > fromTs)
      .map((p) => ({ x: new Date(p.ts).getTime(), y: p.value }));
    if (!pts.length) pts.push({ x: fromTs.getTime() + horizonMin * 60000, y: serie.forecast });
    return [{ x: fromTs.getTime(), y: fromVal }, ...pts];
  }

  /** Réduit une série {x,y} à ~n points par moyenne (ou max) sur des tranches de temps. */
  function bucket(points, n, useMax = false) {
    if (points.length <= n) return points;
    const size = Math.ceil(points.length / n);
    const out = [];
    for (let i = 0; i < points.length; i += size) {
      const sl = points.slice(i, i + size).filter((p) => p.y !== null && p.y !== undefined);
      if (!sl.length) { out.push({ x: points[i].x, y: null }); continue; }
      const y = useMax ? Math.max(...sl.map((p) => p.y)) : sl.reduce((s, p) => s + p.y, 0) / sl.length;
      out.push({ x: sl[Math.floor(sl.length / 2)].x, y });
    }
    return out;
  }

  /** Coupe la courbe (point null) là où il manque des mesures depuis plus de gapMs. */
  function breakGaps(points, gapMs = 90000) {
    const out = [];
    points.forEach((p, i) => {
      if (i && p.x - points[i - 1].x > gapMs) out.push({ x: points[i - 1].x + 1, y: null });
      out.push(p);
    });
    return out;
  }

  const COLOR = "#1f4e79";

  /** Courbe : série mesurée pleine + prévision pointillée. small=true : sparkline sans axes. */
  function makeChart(canvas, { small = false, step = false, yTicks } = {}) {
    return new Chart(canvas, {
      type: "line",
      data: {
        datasets: [
          { data: [], borderColor: COLOR, borderWidth: small ? 1.25 : 1.5, pointRadius: 0, tension: 0, stepped: step, spanGaps: false },
          { data: [], borderColor: COLOR, borderWidth: small ? 1.25 : 1.5, borderDash: [4, 3], pointRadius: 0, tension: 0 },
        ],
      },
      options: {
        animation: false, // IHM : pas d'animation, mise à jour immédiate
        maintainAspectRatio: false,
        parsing: false,
        normalized: true,
        interaction: { intersect: false, mode: "nearest", axis: "x" },
        plugins: {
          legend: { display: false },
          tooltip: small ? { enabled: false } : {
            callbacks: {
              title: (items) => hhmm(items[0].parsed.x),
              label: (item) => `${item.dataset.borderDash ? "prévu" : "mesuré"} : ${Number(item.parsed.y).toFixed(1)}`,
            },
          },
        },
        scales: {
          x: { type: "linear", display: !small, ticks: { color: "#565d64", maxTicksLimit: 7, maxRotation: 0, font: { size: 11 }, callback: hhmm }, grid: { color: "#d4d7da" } },
          y: { display: !small, grace: "8%", ticks: { color: "#565d64", font: { size: 11 }, ...(yTicks ? { callback: yTicks, stepSize: 1 } : {}) }, grid: { color: "#d4d7da" } },
        },
      },
    });
  }

  // ---------- WebSocket unique ----------

  let retry = 1000;
  function connectWs() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { setWs(true); retry = 1000; };
    ws.onclose = (ev) => {
      // 1008 : session refusée par le serveur -> vérifier (get renvoie vers la connexion si besoin)
      if (ev.code === 1008) get("/auth/me");
      setWs(false);
      setTimeout(connectWs, retry);
      retry = Math.min(retry * 2, 10000);
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      const { type, data } = msg;
      if (type === "measure") showMeasure(data);
      else if (type === "state") showState(data);
      else if (type === "alert") putAlert(data);
      else if (type === "alert_ack") ackAlert(data);
      else if (type === "analysis") { store.analysis = data; bus.emit("analysis", data); }
    };
  }

  // ---------- Démarrage ----------

  async function pollForecast() {
    const f = await get("/forecast?horizon=10");
    if (f) { store.forecast = f; bus.emit("forecast", f); }
  }

  async function logout() {
    await post("/auth/logout");
    location.replace("/login.html");
  }

  async function init() {
    setInterval(() => { $("clock").textContent = new Date().toLocaleTimeString("fr-FR"); }, 1000);
    $("logout").addEventListener("click", logout);
    get("/auth/me").then((me) => { if (me) $("user").textContent = me.user; });
    setInterval(refreshLast, 1000);

    const [status, metrics, alerts, analysis] = await Promise.all([
      get("/status"), get("/metrics?minutes=10"), get("/alerts?limit=200"), get("/analysis"),
    ]);
    if (metrics && metrics.length) {
      store.measures.push(...metrics.slice(-MAX_MEASURES));
      store.last = metrics[metrics.length - 1];
      refreshLast();
    }
    if (status) showState(status);
    if (alerts) alerts.forEach((a) => store.alerts.set(a.id, a));
    refreshAlarmCell();
    bus.emit("alerts");
    if (analysis) { store.analysis = analysis; bus.emit("analysis", analysis); }

    connectWs();
    checkVision();
    setInterval(checkVision, 3000);
    pollForecast();
    setInterval(pollForecast, 10000);
  }

  return { pages: {}, API, $, h, clock, num, rel, bus, get, post, store, unacked, alarmRow, openSnap,
    commandsPanel, makeChart, forecastPath, bucket, breakGaps, init, SENSOR_NAMES };
})();
