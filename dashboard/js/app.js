// Sentinel-X — routeur par hash : #/ (ensemble), #/capteurs, #/camera, #/alarmes, #/systeme
(() => {
  const TITLES = { "": "Vue d'ensemble", capteurs: "Capteurs", camera: "Caméra", alarmes: "Alarmes", systeme: "Système" };
  let current = null;

  function route() {
    let r = location.hash.replace(/^#\/?/, "");
    if (!(r in TITLES)) r = "";
    if (r === current) return;
    if (current !== null) SX.pages[current].hide();
    current = r;
    document.querySelectorAll(".page").forEach((p) => { p.hidden = p.id !== `page-${r}`; });
    document.querySelectorAll(".tabs a").forEach((a) => {
      if (a.dataset.route === r) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    document.title = `${TITLES[r]} · Sentinel-X`;
    document.body.dataset.route = r; // la vue d'ensemble occupe toute la fenêtre (voir style.css)
    SX.pages[r].show();
  }

  for (const [r, page] of Object.entries(SX.pages)) page.init(document.getElementById(`page-${r}`));
  window.addEventListener("hashchange", route);
  SX.init();
  route();
})();
