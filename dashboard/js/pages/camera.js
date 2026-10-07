// Page 3 — Caméra : flux en grand, temps d'inférence, personnes, galerie des intrusions.
SX.pages.camera = (() => {
  const { h, num, store, bus, get } = SX;
  let el = {}, timers = [], visible = false;

  function setStream() {
    const on = visible && store.visionActive;
    el.img.hidden = !on;
    el.empty.hidden = on;
    // Le flux n'est ouvert que sur cette page (limite de connexions du navigateur)
    if (on) { if (!el.img.getAttribute("src")) el.img.src = `${SX.API}/vision/stream?t=${Date.now()}`; }
    else if (el.img.getAttribute("src")) el.img.removeAttribute("src");
  }

  async function pollStats() {
    const s = await get("/vision/stats");
    const run = !!s?.active;
    el.inf.textContent = run && s.inference_ms !== null ? `${num(s.inference_ms, 0)} ms` : "—";
    el.inf.classList.toggle("warn-text", run && s.inference_ms !== null && s.inference_ms >= 100);
    el.persons.textContent = run && s.persons !== null ? s.persons : "—";
  }

  async function loadGallery() {
    const list = await get("/alerts?limit=200&source=vision");
    el.gallery.replaceChildren();
    const shots = (list || []).filter((a) => a.snapshot);
    el.galleryCount.textContent = list ? `${shots.length} capture${shots.length > 1 ? "s" : ""}` : "indisponible";
    if (!shots.length) el.gallery.append(h("p", "empty-note", "Aucune capture d'intrusion."));
    shots.forEach((a) => {
      const img = h("img");
      img.src = a.snapshot;
      img.alt = `Intrusion de ${SX.clock(a.ts)}`;
      img.loading = "lazy";
      const b = h("button", "thumb", img, h("span", null, `${new Date(a.ts).toLocaleDateString("fr-FR")} ${SX.clock(a.ts)}`));
      b.addEventListener("click", () => SX.openSnap(a.snapshot));
      el.gallery.append(b);
    });
  }

  function init(root) {
    el.img = h("img");
    el.img.alt = "Flux de la webcam analysé par l'IA";
    el.img.hidden = true;
    el.empty = h("div", "video-empty", h("p", null, "Vision arrêtée : aucun flux."),
      h("code", null, "python detect.py --api http://localhost:8000/api/v1/alerts"));
    el.inf = h("td", "val", "—");
    el.persons = h("td", "val", "—");
    const stats = h("section", "panel", h("h2", null, "Vision"),
      h("table", "kv", h("tbody", null,
        h("tr", null, h("th", null, "Inférence", h("small", null, "objectif < 100 ms")), el.inf),
        h("tr", null, h("th", null, "Personnes en ce moment"), el.persons))));
    el.galleryCount = h("small", null, "");
    el.gallery = h("div", "gallery");
    root.append(
      h("div", "grid-cam",
        h("section", "panel", h("h2", null, "Flux en direct"), h("div", "video-frame wide", el.img, el.empty)),
        h("div", "stack-top", stats,
          h("section", "panel", h("h2", null, "Captures d'intrusion", el.galleryCount), el.gallery))));
    bus.on("vision", setStream);
    bus.on("alerts", (a) => { if (visible && a && a.source === "vision") loadGallery(); });
  }
  function show() {
    visible = true;
    setStream(); pollStats(); loadGallery();
    timers = [setInterval(pollStats, 2000)];
  }
  function hide() { visible = false; timers.forEach(clearInterval); timers = []; setStream(); }
  return { init, show, hide };
})();
