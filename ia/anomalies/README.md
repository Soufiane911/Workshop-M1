# Sentinel-X — Maintenance prédictive (Isolation Forest)

Détecte une **dérive lente** de l'environnement (ex. température qui monte doucement + micro-dérive du gaz corrélée) **avant** qu'un seuil critique soit franchi. Aucune règle statique du type `temp > 40` : c'est un modèle appris sur le fonctionnement normal.

## Fonctionnement

1. Le détecteur écoute `sentinel/capteurs` et garde une fenêtre glissante de 30 mesures (~1 min).
2. Features par fenêtre : `temp_mean`, `temp_slope` (°C/min, moindres carrés), `temp_std`, `hum_slope`, `gaz_mean`, `gaz_slope`, `gaz_std`, `corr_temp_gaz` (Pearson, 0 si indéfini). Capteur désactivé (`null`) : features NaN, remplacées par la moyenne d'entraînement (valeur neutre).
3. Pipeline scikit-learn : `SimpleImputer` -> `StandardScaler` -> `IsolationForest(n_estimators=200)`, plus une **enveloppe elliptique** (`EllipticEnvelope`, distance de Mahalanobis robuste) apprise sur les mêmes features normalisées, avec la même contamination.
4. Score 0..1 : `score = 1 / (1 + exp(20 * d))` avec `d = min(d_IF, d_env)` : `d_IF` = `decision_function` de l'Isolation Forest, `d_env = 0,1 × (m²_seuil − m²) / m²_seuil` (m² = distance de Mahalanobis au carré, `m²_seuil` appris). d > 0 normal, d = 0 frontière, d < 0 anomalie. Donc 0,5 = frontière, > 0,9 = très anormal.

   Pourquoi deux modèles : l'Isolation Forest découpe l'espace **dans les limites des données d'entraînement**. Hors de ce domaine il sature : une température moyenne de 35 °C n'y est pas plus anormale que la plus haute vue en fonctionnement normal. Mesuré avec l'IF seul : pendant l'incident, seulement 31 % des fenêtres restaient en anomalie (10 % en surchauffe), avec 29 entrées en anomalie, donc des alertes à répétition. L'enveloppe, elle, s'écarte d'autant plus que la dérive progresse : l'état reste `anomalie` tant que l'incident dure. Les deux frontières sont apprises sur les données normales, aucun seuil n'est fixé à la main.
5. États : `normal` (score < 0,5), `derive` (score >= 0,5), `anomalie` (3 fenêtres consécutives >= 0,5 ; retour à normal après 3 mesures calmes). Entrée en `anomalie` : alerte `anomalie / derive_environnement` (warning, critical si score >= 0,9), cooldown 60 s. L'explication française vient des features les plus éloignées de l'entraînement (z-score).

**Principe de l'Isolation Forest** : on découpe l'espace des features avec des seuils aléatoires. Un point atypique est isolé en très peu de coupures (chemin court dans l'arbre), un point normal, noyé dans la masse, demande beaucoup de coupures. Le chemin moyen sur 200 arbres donne le score d'anomalie. Seules des données normales sont nécessaires pour l'entraînement.

## Utilisation

```bash
cd ia/anomalies
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1. Données normales (2 h simulées, quelques secondes)
../../infra/simulator/.venv/bin/python ../../infra/simulator/simulator.py --fast --duration 7200 --seed 1 --csv data/normal.csv
# 2. Entraînement -> model.joblib (+ model.json)
.venv/bin/python train.py --csv data/normal.csv --contamination 0.003
# 3. Rapport d'évaluation (génère les scénarios dans data/)
.venv/bin/python evaluate.py
# 4. Service temps réel
.venv/bin/python detector.py --api http://localhost:8000/api/v1 --mqtt-host localhost
```

Options du détecteur : `--api`, `--mqtt-host`, `--mqtt-port`, `--model`, `--window`, `--consecutive`.
Les envois à l'API sont non bloquants ; si `/analysis` ou `/alerts` répond une erreur, elle est affichée (au plus toutes les 30 s) et le détecteur continue.

## Ré-entraînement sur les données réelles du boîtier

Le modèle actuel est entraîné sur le simulateur. Avec le vrai boîtier : laisser tourner en conditions normales (plusieurs heures, idéalement jour + nuit), enregistrer au format `ts,temp,hum,gaz,presence,phase` (colonne `phase` = `normal`), puis :

```bash
.venv/bin/python train.py --csv donnees_reelles.csv --use-ts --contamination 0.01
```

Le bruit et les cycles réels du DHT22/MQ-2 remplaceront ceux du simulateur.

## Résultats (modèle simulateur, 2 h normal, contamination 0,003, mesure toutes les 2 s)

Début d'incident à t = 0 ; le seuil naïf (`temp > 40` ou `gaz > 600`) n'est donné qu'à titre de comparaison.
Dérives du simulateur : +0,3 °C/min (incident, surchauffe), +3 /min de gaz (incident), +60 /min (fuite).

| Scénario   | IA : dérive | IA : anomalie | Seuil naïf | Avance de l'IA   | Maintien | Entrées en anomalie |
|------------|-------------|---------------|------------|------------------|----------|---------------------|
| incident   | +118 s      | +122 s        | +3670 s    | 3548 s (~59 min) | 100 %    | 1                   |
| surchauffe | +194 s      | +198 s        | +3662 s    | 3464 s (~58 min) | 99 %     | 2                   |
| fuite_gaz  | +18 s       | +22 s         | +296 s     | 274 s            | 100 %    | 1                   |

Maintien = part des fenêtres en anomalie après la première détection ; entrées = nombre de passages en anomalie pendant l'incident (une alerte chacun, au plus une par minute).
Faux positifs sur 2 h de run normal indépendant : 0 alerte, 0 % de fenêtres en anomalie, 0,22 % en dérive (8 fenêtres isolées).
L'incident est repéré quand la température a pris ~0,6 °C et le gaz ~6 unités : la micro-dérive corrélée suffit, bien avant tout seuil. Avec `--contamination 0.01` (défaut de train.py), on obtient 1,2 % de fenêtres en anomalie et 4 alertes sur 2 h : à éviter en démonstration.

## Limites

- Entraîné sur des données simulées : à ré-entraîner sur le boîtier réel.
- Le temps est reconstitué à 2 s/mesure à l'entraînement ; en direct on utilise l'heure d'arrivée. Un intervalle très différent (ex. 1 s) change légèrement les pentes/bruit.
- Le mode `--fast` du simulateur écrit un `ts` en temps simulé, cohérent ; l'entraînement reconstitue tout de même le temps (`i × interval`) par défaut, `--use-ts` lit la colonne `ts`.
- En direct, le détecteur s'appuie sur l'heure d'arrivée des messages : après une coupure, la fenêtre mélange deux sessions pendant ~1 min (dérive brève possible).
