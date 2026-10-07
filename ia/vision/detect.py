"""Sentinel-X — Détection de présence humaine sur la webcam (YOLOv8).

Capte le flux de la webcam, redimensionne en 640x480, détecte les personnes
et envoie une alerte à l'API quand une présence dure plus de N secondes.

Usage :
    python detect.py                          # webcam 0, sans API
    python detect.py --camera 1               # autre webcam (ex. webcam USB)
    python detect.py --api http://localhost:8000/api/v1/alerts   # alertes + vidéo vers le dashboard
    python detect.py --zone                   # alerte seulement dans la zone interdite

Touches : q = quitter, s = capture manuelle.
"""

import argparse
import json
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import cv2
from ultralytics import YOLO

FRAME_W, FRAME_H = 640, 480
PERSON_CLASS = 0  # "person" dans COCO
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

# Zone interdite (x1, y1, x2, y2) en pixels sur l'image 640x480
FORBIDDEN_ZONE = (320, 0, 640, 480)


def parse_args():
    p = argparse.ArgumentParser(description="Détection de présence humaine Sentinel-X")
    p.add_argument("--camera", type=int, default=0, help="index de la webcam (défaut : 0)")
    p.add_argument("--model", default="yolov8n.pt", help="modèle YOLO (défaut : yolov8n.pt)")
    p.add_argument("--conf", type=float, default=0.5, help="confiance minimale (défaut : 0.5)")
    p.add_argument("--delay", type=float, default=3.0, help="secondes de présence avant alerte (défaut : 3)")
    p.add_argument("--cooldown", type=float, default=30.0, help="secondes entre deux alertes (défaut : 30)")
    p.add_argument("--api", default=None, help="URL de POST /api/v1/alerts (désactivé si absent)")
    p.add_argument("--zone", action="store_true", help="ne compter que les personnes dans la zone interdite")
    p.add_argument("--no-window", action="store_true", help="ne pas afficher la fenêtre vidéo")
    p.add_argument("--no-stream", action="store_true", help="ne pas envoyer la vidéo au dashboard")
    p.add_argument("--stream-fps", type=float, default=5.0, help="images par seconde envoyées (défaut : 5)")
    return p.parse_args()


class FrameSender:
    """Envoie la dernière image annotée à l'API, sans jamais bloquer la détection.

    Si l'envoi précédent n'est pas fini, l'image est simplement remplacée par la plus récente.
    """

    def __init__(self, url, fps):
        self.url = url
        self.period = 1 / fps
        self.latest = None
        self.event = threading.Event()
        self.last_error = 0.0
        self.last_submit = 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, frame):
        # Encodage JPEG seulement au rythme du flux : rien de superflu dans la boucle de détection
        now = time.monotonic()
        if now - self.last_submit < self.period:
            return
        self.last_submit = now
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            self.latest = buf.tobytes()
            self.event.set()

    def _run(self):
        while True:
            self.event.wait()
            self.event.clear()
            jpeg, self.latest = self.latest, None
            if jpeg is None:
                continue
            start = time.monotonic()
            try:
                req = urllib.request.Request(self.url, data=jpeg, method="POST",
                                             headers={"Content-Type": "image/jpeg"})
                urllib.request.urlopen(req, timeout=2).close()
            except Exception as e:
                if time.monotonic() - self.last_error > 10:  # évite d'inonder la console
                    print(f"[API] échec de l'envoi vidéo : {e}")
                    self.last_error = time.monotonic()
            time.sleep(max(0.0, self.period - (time.monotonic() - start)))


class StatsSender:
    """Envoie environ une fois par seconde les stats de performance (moyennes glissantes) à l'API.

    Non bloquant : l'envoi part dans un thread, les erreurs sont affichées au plus toutes les 10 s.
    """

    def __init__(self, url, model, conf):
        self.url = url
        self.model = model
        self.conf = conf
        self.infer = deque(maxlen=30)
        self.fps = deque(maxlen=30)
        self.last_sent = 0.0
        self.last_error = 0.0

    def update(self, infer_ms, fps, persons):
        self.infer.append(infer_ms)
        self.fps.append(fps)
        now = time.monotonic()
        if now - self.last_sent < 1.0:
            return
        self.last_sent = now
        payload = {
            "inference_ms": round(sum(self.infer) / len(self.infer), 1),
            "fps": round(sum(self.fps) / len(self.fps), 1),
            "persons": persons,
            "model": self.model,
            "conf": self.conf,
        }
        threading.Thread(target=self._post, args=(payload,), daemon=True).start()

    def _post(self, payload):
        try:
            req = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=2).close()
        except Exception as e:
            if time.monotonic() - self.last_error > 10:  # évite d'inonder la console
                print(f"[API] échec de l'envoi des stats : {e}")
                self.last_error = time.monotonic()


def in_zone(box, zone):
    """Vrai si le centre de la boîte est dans la zone."""
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    zx1, zy1, zx2, zy2 = zone
    return zx1 <= cx <= zx2 and zy1 <= cy <= zy2


def send_alert(api_url, payload):
    """Envoie l'alerte dans un thread pour ne pas bloquer la vidéo."""
    def _post():
        try:
            req = urllib.request.Request(
                api_url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                print(f"[API] alerte envoyée ({resp.status})")
        except Exception as e:
            print(f"[API] échec de l'envoi : {e}")

    threading.Thread(target=_post, daemon=True).start()


def save_snapshot(frame):
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    path = SNAPSHOT_DIR / f"intrus_{datetime.now():%Y%m%d_%H%M%S}.jpg"
    cv2.imwrite(str(path), frame)
    return path


def draw(frame, persons, zone_on, alarm, infer_ms, fps):
    if zone_on:
        x1, y1, x2, y2 = FORBIDDEN_ZONE
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(frame, "ZONE INTERDITE", (x1 + 8, y1 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    for (x1, y1, x2, y2), conf, counted in persons:
        color = (0, 0, 255) if counted else (0, 200, 0)
        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
        cv2.putText(frame, f"personne {conf:.0%}", (int(x1), int(y1) - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    status = "ALERTE INTRUSION" if alarm else "SURVEILLANCE"
    color = (0, 0, 255) if alarm else (0, 200, 0)
    cv2.putText(frame, status, (10, FRAME_H - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    perf_color = (0, 200, 0) if infer_ms < 100 else (0, 140, 255)
    cv2.putText(frame, f"inference {infer_ms:.0f} ms | {fps:.0f} FPS", (10, FRAME_H - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, perf_color, 2)


def main():
    args = parse_args()
    model = YOLO(args.model)  # téléchargé automatiquement au premier lancement

    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    if not cap.isOpened():
        raise SystemExit(f"Impossible d'ouvrir la webcam {args.camera}. Essayez --camera 1.")

    sender = None
    stats = None
    if args.api and not args.no_stream:
        frame_url = args.api.rsplit("/alerts", 1)[0] + "/vision/frame"
        sender = FrameSender(frame_url, args.stream_fps)
        print(f"Vidéo envoyée au dashboard : {frame_url}")
        stats_url = args.api.rsplit("/alerts", 1)[0] + "/vision/stats"
        stats = StatsSender(stats_url, args.model, args.conf)

    presence_since = None   # début de la présence en cours
    last_alert = 0.0
    prev_time = time.perf_counter()
    print("Détection lancée. q = quitter, s = capture.")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Flux webcam interrompu.")
            break

        # Bridage de la taille pour rester sous 100 ms par trame
        frame = cv2.resize(frame, (FRAME_W, FRAME_H))

        t0 = time.perf_counter()
        result = model(frame, classes=[PERSON_CLASS], conf=args.conf, verbose=False)[0]
        infer_ms = (time.perf_counter() - t0) * 1000

        persons = []
        for box, conf in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist()):
            counted = in_zone(box, FORBIDDEN_ZONE) if args.zone else True
            persons.append((box, conf, counted))
        suspects = [p for p in persons if p[2]]

        # Présence suspecte = au moins une personne comptée pendant --delay secondes
        now = time.time()
        if suspects:
            presence_since = presence_since or now
        else:
            presence_since = None
        alarm = presence_since is not None and now - presence_since >= args.delay

        cur = time.perf_counter()
        fps = 1 / max(cur - prev_time, 1e-6)
        prev_time = cur

        # Annoter avant l'alerte : l'API prend l'image courante comme capture de l'intrus
        if sender or not args.no_window:
            draw(frame, persons, args.zone, alarm, infer_ms, fps)
        if sender:
            sender.submit(frame)
            stats.update(infer_ms, fps, len(persons))

        if alarm and now - last_alert >= args.cooldown:
            last_alert = now
            snap = save_snapshot(frame)
            best = max(p[1] for p in suspects)
            print(f"[ALERTE] {len(suspects)} personne(s) depuis {now - presence_since:.0f}s — {snap.name}")
            if args.api:
                send_alert(args.api, {
                    "source": "vision",
                    "type": "intrusion",
                    "level": "critical",
                    "message": f"Présence humaine détectée depuis {now - presence_since:.0f}s",
                    "persons": len(suspects),
                    "confidence": round(best, 2),
                    "snapshot": snap.name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        if not args.no_window:
            cv2.imshow("Sentinel-X - Vision", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                print(f"Capture : {save_snapshot(frame).name}")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
