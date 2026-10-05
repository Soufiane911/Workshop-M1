# Intelligence Artificielle

- `vision/` : détection de présence humaine sur la webcam USB (YOLOv8 / OpenCV), images 640x480, < 100 ms par trame
- `anomalies/` : détection d'anomalies sur les séries temporelles des capteurs (Isolation Forest, pas de seuils `if` statiques)

Les deux envoient leurs alertes à l'API via `POST /api/v1/alerts`.
