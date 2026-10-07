// Page 4 — Alarmes : journal complet, filtre « non acquittées ».
SX.pages.alarmes = (() => {
  const { h, get, bus } = SX;
  let el = {}, visible = false, timer = null;

  async function load() {
    const q = new URLSearchParams({ limit: "200" });
    if (el.unacked.checked) q.set("unacked", "true");
    const list = await get(`/alerts?${q}`);
    el.body.replaceChildren();
    el.count.textContent = list ? `${list.length} alarme${list.length > 1 ? "s" : ""}` : "";
    const empty = (text) => {
      const td = h("td", null, text);
      td.colSpan = 6;
      el.body.append(h("tr", "empty", td));
    };
    if (!list) return empty("Journal indisponible.");
    list.forEach((a) => el.body.append(SX.alarmRow(a, true, (t) => { el.msg.textContent = t; })));
    if (!list.length) empty("Aucune alarme.");
  }

  function laterLoad() { clearTimeout(timer); timer = setTimeout(load, 300); }

  function init(root) {
    el.unacked = h("input");
    el.unacked.type = "checkbox";
    el.count = h("span", "muted");
    el.msg = h("span", "muted");
    el.msg.setAttribute("role", "status");
    el.body = h("tbody");
    root.append(h("section", "panel",
      h("h2", null, "Journal des alarmes"),
      h("div", "filters", h("label", "check", el.unacked, " non acquittées seulement"), el.count, el.msg),
      h("div", "table-scroll tall", h("table", "alarms full",
        h("thead", null, h("tr", null, ...["Heure", "Priorité", "Source", "Événement", "Capture", "Acquittement"].map((t) => h("th", null, t)))),
        el.body))));
    el.unacked.addEventListener("change", load);
    bus.on("alerts", () => { if (visible) laterLoad(); });
  }
  function show() { visible = true; load(); }
  function hide() { visible = false; }
  return { init, show, hide };
})();
