"""Sentinel-X — Évaluation du détecteur : délai de détection vs seuil naïf.

Génère (via le simulateur, mode --fast) un run par scénario + un run normal
indépendant, rejoue chaque run dans le détecteur et affiche un rapport :
  - délai (s) après le début de l'incident avant « derive » puis « anomalie » ;
  - moment où un seuil naïf (temp > 40 ou gaz > 600) aurait déclenché
    (comparaison uniquement, jamais utilisé pour alerter) ;
  - maintien : part des fenêtres en « anomalie » après la première détection, et
    nombre d'entrées en anomalie (= alertes potentielles) pendant l'incident ;
  - taux de faux positifs sur le run normal.

Usage :
    python evaluate.py                 # génère les CSV dans data/ puis évalue
    python evaluate.py --regen         # régénère les CSV
"""

import argparse
import subprocess
import sys
from pathlib import Path

import features as ft
from detector import Analyseur

ICI = Path(__file__).parent
SIM = ICI.parent.parent / "infra" / "simulator"
DATA = ICI / "data"
SCENARIOS = ["incident", "surchauffe", "fuite_gaz"]
START_AFTER = 300   # s de normal avant l'incident
DUREE = 4200        # s par run : à +0,3 °C/min, le seuil naïf de 40 °C tombe vers +60 min


def generer(nom, scenario, duree, start_after, seed, interval, regen):
    csv = DATA / f"{nom}.csv"
    if csv.exists() and not regen:
        return csv
    DATA.mkdir(exist_ok=True)
    py = SIM / ".venv" / "bin" / "python"
    subprocess.run([str(py if py.exists() else sys.executable), str(SIM / "simulator.py"),
                    "--scenario", scenario, "--fast", "--duration", str(duree),
                    "--start-after", str(start_after), "--interval", str(interval),
                    "--seed", str(seed), "--csv", str(csv)],
                   check=True, stdout=subprocess.DEVNULL)
    return csv


def rejouer(modele, mesures, consecutive):
    an = Analyseur(modele, consecutive=consecutive)
    return [an.push(*m) for m in mesures]


def premier(cond, debut=0):
    for i in range(debut, len(cond)):
        if cond[i]:
            return i
    return None


def fmt(i, debut, interval):
    return "jamais" if i is None else f"{(i - debut) * interval:+.0f} s"


def main():
    p = argparse.ArgumentParser(description="Évaluation du détecteur Sentinel-X")
    p.add_argument("--model", type=Path, default=ICI / "model.joblib")
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--consecutive", type=int, default=3)
    p.add_argument("--regen", action="store_true")
    args = p.parse_args()
    iv = args.interval

    print("=== Délai de détection après le début de l'incident ===")
    print(f"{'scénario':<12}{'IA : dérive':>13}{'IA : anomalie':>15}{'seuil naïf':>13}{'avance IA':>12}"
          f"{'maintien':>10}{'entrées':>9}")
    for k, sc in enumerate(SCENARIOS):
        csv = generer(f"eval_{sc}", sc, DUREE, START_AFTER, 100 + k, iv, args.regen)
        mesures, phases = ft.lire_csv(csv, iv)
        debut = premier([ph != "normal" for ph in phases])
        res = rejouer(args.model, mesures, args.consecutive)
        derive = premier([r is not None and r["state"] != "normal" for r in res], debut)
        anom = premier([r is not None and r["state"] == "anomalie" for r in res], debut)
        naif = premier([(m[1] is not None and m[1] > 40) or (m[3] is not None and m[3] > 600)
                        for m in mesures], debut)
        avance = "-" if anom is None or naif is None else f"{(naif - anom) * iv:.0f} s"
        avant = sum(1 for r in res[:debut] if r is not None and r["state"] == "anomalie")
        suite = [r["state"] for r in res[anom:]] if anom is not None else []
        maintien = f"{100 * suite.count('anomalie') / len(suite):.0f} %" if suite else "-"
        entrees = sum(1 for a, b in zip(res[debut - 1:], res[debut:])
                      if b is not None and b["state"] == "anomalie" and (a is None or a["state"] != "anomalie"))
        print(f"{sc:<12}{fmt(derive, debut, iv):>13}{fmt(anom, debut, iv):>15}{fmt(naif, debut, iv):>13}{avance:>12}"
              f"{maintien:>10}{entrees:>9}"
              + (f"   [!] {avant} faux positifs avant l'incident" if avant else ""))

    csv = generer("eval_normal", "normal", 7200, 30, 999, iv, args.regen)
    mesures, _ = ft.lire_csv(csv, iv)
    res = [r for r in rejouer(args.model, mesures, args.consecutive) if r is not None]
    n = len(res)
    nd = sum(r["state"] != "normal" for r in res)
    na = sum(r["state"] == "anomalie" for r in res)
    episodes = sum(1 for a, b in zip(res, res[1:]) if a["state"] != "anomalie" and b["state"] == "anomalie")
    print("\n=== Faux positifs sur un run normal indépendant ===")
    print(f"{n} fenêtres ({n * iv / 3600:.1f} h) : "
          f"{nd} en dérive ou plus ({100 * nd / n:.2f} %), "
          f"{na} en anomalie ({100 * na / n:.2f} %), {episodes} alerte(s) déclenchée(s)")


if __name__ == "__main__":
    main()
