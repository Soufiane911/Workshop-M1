FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY models ./models
# exécution sans privilèges root (hardening)
RUN useradd -r -u 10001 sentinel
USER sentinel
CMD ["python", "-m", "app.mqtt_service"]
