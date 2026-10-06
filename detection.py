import time
import cv2
from ultralytics import YOLO

CAM_INDEX = 0
INFER_SIZE = 320   # essayez 256 si c'est trop lent
BUDGET_MS = 100

model = YOLO("yolov8n.pt")

# Recherche d'une camera utilisable (2 pilotes, plusieurs index)
cap = None
for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
    for index in (CAM_INDEX, 1, 2):
        c = cv2.VideoCapture(index, backend)
        if c.isOpened() and c.read()[0]:
            cap = c
            print(f"Camera trouvee : index={index}")
            break
        c.release()
    if cap is not None:
        break

if cap is None:
    print("ERREUR : aucune camera utilisable")
    raise SystemExit

cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

print("Appuyez sur 'q' dans la fenetre video pour quitter")

while True:
    t0 = time.perf_counter()

    ok, frame = cap.read()
    if not ok:
        print("ERREUR : lecture camera impossible")
        break

    frame = cv2.resize(frame, (640, 480))

    result = model.predict(frame, imgsz=INFER_SIZE, classes=[0],
                           conf=0.5, verbose=False)[0]

    for box in result.boxes:
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(frame, "INTRUS", (x1, max(y1 - 8, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

    ms = (time.perf_counter() - t0) * 1000
    statut = "OK" if ms < BUDGET_MS else "TROP LENT"
    print(f"{ms:.0f} ms -> {statut} | personnes : {len(result.boxes)}")

    cv2.putText(frame, f"{ms:.0f} ms", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.imshow("Sentinel-X", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()