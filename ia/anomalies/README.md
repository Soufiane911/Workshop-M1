# SENTINEL-X — IA : Maintenance Prédictive

Module « Maintenance Prédictive » du pôle **EISI IA** (Workshop M1 2026-27).
Il analyse les séries temporelles envoyées par l'ESP8266 (DHT22 température/humidité, MQ-2 gaz, PIR)
et détecte les **anomalies cinétiques** *avant* qu'un seuil critique ne soit franchi.
Conformément au sujet : **aucun `if temp > X`** — la décision vient d'un modèle (Isolation Forest, scikit-learn).

## Principe

1. **Fenêtre glissante** de 30 mesures (1 min à 1 mesure / 2 s), évaluée toutes les 5 mesures.
2. **18 features** par fenêtre (`app/features.py`) : moyenne, écart-type (échelle log), **pente**, étendue et variation max
   pour température / humidité / gaz, **corrélations température↔gaz et température↔humidité**, taux de présence PIR.
3. **Isolation Forest** (non supervisé) entraîné **uniquement sur du fonctionnement normal**, précédé d'un `StandardScaler`.
4. **Seuils sur le score du modèle** (pas sur les capteurs) déduits de la distribution des scores d'entraînement :
   `warning` (0,5ᵉ percentile) et `critical`.
5. **Anti faux-positifs** : alerte si ≥ 3 fenêtres anormales consécutives.
6. **Explicabilité** : chaque résultat renvoie les 3 features les plus atypiques (utile pour le dashboard et l'oral).

## Démarrage rapide

```bash
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt

python -m app.train      # génère données simulées, entraîne, évalue -> models/ + reports/metrics.json
python -m app.replay     # rejoue un flux avec anomalies et affiche les alertes (démo hors-ligne)
python -m pytest -q      # tests
```

## Intégration avec les autres briques

**Entrée** — topic MQTT `sentinel/<device_id>/sensors` (à valider avec l'équipe firmware) :
```json
{"device_id": "esp-01", "ts": 1760000000, "temperature": 22.4, "humidity": 51.2, "gas": 303, "pir": 0}
```

**Sortie** — topic `sentinel/<device_id>/ai/maintenance`, publié toutes les 5 mesures :
```json
{"device_id": "esp-01", "ts": 1760000010, "score": -0.0912, "level": "warning", "alert": true,
 "top_features": [{"name": "temperature_slope", "z": 6.1}, {"name": "gas_mean", "z": 4.3}, {"name": "temperature_range", "z": 3.9}]}
```
`level` ∈ `normal | warning | critical` ; `alert` = vrai après 3 fenêtres anormales d'affilée.
Quand `alert` est vrai, le service fait aussi un `POST` vers l'API (`API_URL`, ex. `/api/v1/alerts`) avec
`{source, device_id, ts, level, score, details}` → **à aligner avec le schéma défini par l'équipe DEV**.

**Lancement** : `python -m app.mqtt_service` (config par variables d'environnement, voir `.env.example`).
Support TLS (MQTTS) via `MQTT_CA_CERT`. **Ne jamais committer `.env`.**

**Docker (pour l'équipe INFRA)** — exemple de service à ajouter au `docker-compose.yml` :
```yaml
  ai-maintenance:
    build: ./ia-maintenance-predictive
    env_file: .env
    depends_on: [mosquitto]
    restart: unless-stopped
```

## Résultats (sur données **simulées**, `reports/metrics.json`)

| Indicateur | Valeur |
|---|---|
| Précision (par fenêtre) | 0,94 |
| Rappel (par fenêtre) | 0,62 |
| Taux de faux positifs (par fenêtre) | 0,8 % |
| Événements détectés | **35 / 35** (dérive 9/9, fuite gaz 9/9, capteur figé 9/9, pic 8/8) |
| Délai moyen de détection | dérive ≈ 62 s, fuite gaz ≈ 17 s, capteur figé ≈ 61 s, pic ≈ 8 s |
| Dérive lente | détectée en moyenne à ≈ 23,3 °C alors que l'événement culmine en moyenne à ≈ 28,0 °C |

Le rappel par fenêtre est plus bas que le rappel par événement car le début des anomalies (encore subtil) n'est pas flaggé tout de suite.
Sur ~44 h de fonctionnement normal simulé, on observe ~2 épisodes de fausse alerte.

## Limites (à dire honnêtement au jury)

- Les métriques ci-dessus portent sur des **données simulées** (`app/simulate.py`). Dès que l'ESP8266 est câblé :
  collecter 30–60 min de mesures normales dans un CSV (mêmes colonnes) et **réentraîner** (`python -m app.train` en adaptant le chargement).
- La période d'échantillonnage (2 s) et la fenêtre (30) sont dans `app/config.py` : à aligner avec le firmware.
- Le modèle sérialisé (`joblib`) dépend de la version de scikit-learn : garder celle de `requirements.txt`.
- Charger un fichier `.joblib` = exécuter du code désérialisé : ne charger que des modèles produits par l'équipe.

## Structure

```
app/config.py        paramètres (fenêtre, pas, topics)
app/simulate.py      simulateur ESP8266 (normal + 4 types d'anomalies)
app/features.py      extraction de features sur fenêtre glissante
app/train.py         entraînement Isolation Forest + évaluation
app/detector.py      détecteur temps réel (push mesure par mesure)
app/mqtt_service.py  service MQTT/MQTTS + POST vers l'API
app/replay.py        démo hors-ligne
tests/               tests pytest
```
