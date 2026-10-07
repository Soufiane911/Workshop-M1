# Détecteur d'anomalies Sentinel-X.
# Contexte de build = racine du repo (le simulateur sert à générer les données d'entraînement) :
#   docker build -f ia/anomalies/Dockerfile .
# Le modèle n'est pas commité : il est entraîné ici sur 2 h de fonctionnement normal simulé
# (graine fixe -> même modèle à chaque build). Pour le boîtier réel, voir README.

FROM python:3.12-slim AS train
WORKDIR /build
COPY ia/anomalies/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY infra/simulator/simulator.py sim/
COPY ia/anomalies/*.py ./
RUN python sim/simulator.py --fast --duration 7200 --seed 1 --csv normal.csv \
    && python train.py --csv normal.csv --contamination 0.003 --out model.joblib

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY ia/anomalies/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ia/anomalies/features.py ia/anomalies/detector.py ./
COPY --from=train /build/model.joblib /build/model.json ./

# Utilisateur non-root (durcissement)
RUN useradd --no-create-home --uid 10001 sentinel
USER sentinel

CMD ["python", "detector.py"]
