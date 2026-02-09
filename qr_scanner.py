import cv2
from pyzbar.pyzbar import decode
import time

CAM_INDEX = 1

cap = cv2.VideoCapture(CAM_INDEX, cv2.CAP_DSHOW)
if not cap.isOpened():
    raise RuntimeError("Kamera nicht geöffnet")

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

last = None
last_t = 0
cooldown = 1.0

print("QR-Scanner (pyzbar) auf externer Kamera – q beendet")

while True:
    ok, frame = cap.read()
    if not ok:
        break

    qrs = decode(frame)
    for qr in qrs:
        data = qr.data.decode("utf-8", errors="replace")
        x, y, w, h = qr.rect
        cv2.rectangle(frame, (x,y), (x+w, y+h), (0,255,0), 2)

        now = time.time()
        if data != last or (now-last_t) > cooldown:
            last, last_t = data, now
            print("QR erkannt:", data)

    cv2.imshow("QR", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()

