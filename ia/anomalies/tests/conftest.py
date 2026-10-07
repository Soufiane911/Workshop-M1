"""Fixtures : un modèle entraîné une seule fois par session, sur des données du simulateur."""

import subprocess
import sys
from pathlib import Path

import pytest

ICI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ICI))

import features as ft  # noqa: E402
import train  # noqa: E402

SIM = ICI.parent.parent / "infra" / "simulator" / "simulator.py"


def simuler(dossier, nom, scenario="normal", duree=1800, seed=1, start_after=300):
    """Lance le simulateur en mode --fast et renvoie les mesures (t, temp, hum, gaz)."""
    csv = dossier / f"{nom}.csv"
    subprocess.run([sys.executable, str(SIM), "--scenario", scenario, "--fast",
                    "--duration", str(duree), "--start-after", str(start_after),
                    "--seed", str(seed), "--csv", str(csv)],
                   check=True, stdout=subprocess.DEVNULL)
    return ft.lire_csv(csv)


@pytest.fixture(scope="session")
def donnees(tmp_path_factory):
    return tmp_path_factory.mktemp("data")


@pytest.fixture(scope="session")
def modele(donnees):
    """Même recette que le Dockerfile : 2 h de normal, contamination 0,003."""
    simuler(donnees, "normal", duree=7200, seed=1)
    pipe, envelope, meta = train.entrainer([donnees / "normal.csv"], contamination=0.003)
    chemin = donnees / "model.joblib"
    import joblib
    joblib.dump({"pipeline": pipe, "envelope": envelope, "meta": meta}, chemin)
    return chemin
