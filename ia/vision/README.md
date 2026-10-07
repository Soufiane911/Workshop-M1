# Vision — détection de présence humaine

Script `detect.py` : webcam → redimensionnement 640x480 → YOLOv8n (classe « person ») → alerte.

## Installation

```bash
cd ia/vision
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Le modèle `yolov8n.pt` (pré-entraîné COCO, ~6 Mo) se télécharge tout seul au premier lancement.

## Lancement

```bash
python detect.py                     # webcam par défaut
python detect.py --camera 1          # webcam USB si plusieurs caméras
python detect.py --zone              # alerte seulement dans la zone interdite (moitié droite)
python detect.py --api http://localhost:8000/api/v1/alerts   # alertes + vidéo dans le dashboard
```

| Option | Défaut | Rôle |
|---|---|---|
| `--delay` | 3 | secondes de présence avant de déclencher l'alerte |
| `--cooldown` | 30 | secondes minimum entre deux alertes |
| `--conf` | 0.5 | confiance minimale de détection |
| `--no-window` | — | pas de fenêtre vidéo (mode serveur) |
| `--no-stream` | — | ne pas envoyer la vidéo au dashboard |
| `--stream-fps` | 5 | images par seconde envoyées au dashboard |

Touches : `q` quitter, `s` capture manuelle. Les captures d'intrus vont dans `snapshots/` (non commité).

## Alerte envoyée à l'API

```json
{
  "source": "vision",
  "type": "intrusion",
  "level": "critical",
  "message": "Présence humaine détectée depuis 3s",
  "persons": 1,
  "confidence": 0.87,
  "snapshot": "intrus_20261005_143012.jpg",
  "timestamp": "2026-10-05T12:30:12+00:00"
}
```
