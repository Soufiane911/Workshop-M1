FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Utilisateur non-root (durcissement) + dossier des captures
RUN useradd --create-home --uid 1000 sentinel \
    && mkdir -p /data/snapshots \
    && chown -R sentinel /data

COPY app ./app
USER sentinel

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
