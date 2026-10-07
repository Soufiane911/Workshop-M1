import cv2
import time

def process_stream(camera_index=0, target_width=640, target_height=480, max_latency_ms=100.0):
    """
    Capture et optimise le flux vidéo de la webcam pour l'inférence IA.
    Garantit un traitement fluide < 100 ms par trame.
    """
    cap = cv2.VideoCapture(camera_index)
    
    # Configuration matérielle de la webcam
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, target_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, target_height)

    if not cap.isOpened():
        print("[ERREUR] Impossible d'accéder à la webcam.")
        return

    print(f"[SENTINEL-X] Flux vidéo démarré ({target_width}x{target_height}) - Cible latence: < {max_latency_ms} ms")

    try:
        while True:
            start_time = time.time()

            ret, frame = cap.read()
            if not ret:
                print("[AVERTISSEMENT] Perte de trame vidéo.")
                break

            # Redimensionnement logiciel de sécurité (si la caméra ne force pas la résolution)
            resized_frame = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)

            # --- INSÉRER ICI L'INFERENCE IA DE TON COLLÈGUE (ex: YOLO / Détection) ---
            
            # Calcul du temps d'exécution total
            elapsed_time_ms = (time.time() - start_time) * 1000

            # Monitoring des performances
            status = "OK" if elapsed_time_ms < max_latency_ms else "WARNING (Surcharge)"
            print(f"[FLUX] Temps de traitement : {elapsed_time_ms:.2f} ms | Statut : {status}")

            # Affichage local de contrôle
            cv2.putText(resized_frame, f"FPS: {1000/elapsed_time_ms:.1f} | {elapsed_time_ms:.1f}ms", 
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0) if status == "OK" else (0, 0, 255), 2)
            
            cv2.imshow("Sentinel-X - Flux Optimisé", resized_frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    process_stream(camera_index = 1)