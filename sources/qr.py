# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
#
# SPDX-License-Identifier: CC0-1.0

import cv2
from pyzbar.pyzbar import decode
import time
import base64
import json
from urllib.parse import urlparse, parse_qs
from pyzbar.pyzbar import ZBarSymbol

import asyncio
import websockets


URL = "ws://localhost:8765"
VALID = 'VALID'
NOT_VALID = 'NOT VALID'

async def send_info(info):
    async with websockets.connect(URL) as websocket:
        print("Connected to server")

        message = {
                "type": "qr",
                "info": info
        }

        await websocket.send(json.dumps(message))
        print("Sent: ", message)

        await asyncio.sleep(1)


CAM_INDEX = 1

# ----------------- Helpers -----------------

def base64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)

def is_dokume_url(s: str) -> bool:
    return s.startswith("https://qr.dokume.net") or s.startswith("http://qr.dokume.net")

# ----------------- Dokume Parser (ohne datetime) -----------------

def parse_dokume_qr(url: str) -> dict:
    """
    Parst Dokume QR-URL und extrahiert wichtige Felder.
    KEINE datetime-Konvertierung.
    """
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    if "s" not in query:
        raise ValueError("Kein JWT ('s' Parameter) in der URL gefunden.")

    jwt_token = query["s"][0]
    parts = jwt_token.split(".")
    if len(parts) != 3:
        raise ValueError("Ungültiges JWT-Format (erwarte 3 Teile).")

    _header_b64, payload_b64, _sig = parts
    payload = json.loads(base64url_decode(payload_b64))

    exp = payload.get("exp")
    if exp is None:
        raise ValueError("Kein 'exp' im JWT-Payload gefunden.")

    return {
        "first_name": payload.get("FN") or "",
        "last_name": payload.get("LN") or "",
        "birth_date": payload.get("DOB"),
        "exp_timestamp": int(exp),
    }

def is_valid(exp_timestamp: int) -> bool:
    """
    True = noch gültig (now <= exp)
    False = abgelaufen (now > exp)
    Vergleich rein auf Unix-Sekundenbasis, ohne datetime.
    """
    now_ts = int(time.time())  # Unix-Sekunden (UTC)
    return now_ts <= exp_timestamp

# ----------------- Kamera Setup -----------------

cap = cv2.VideoCapture(CAM_INDEX, cv2.CAP_DSHOW)
if not cap.isOpened():
    raise RuntimeError("Kamera nicht geöffnet")

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

last = None
last_t = 0
cooldown = 1.0

print("QR-Scanner (pyzbar) – q beendet")

try:
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break

        qrs = decode(frame, symbols=[ZBarSymbol.QRCODE])
        for qr in qrs:
            data = qr.data.decode("utf-8", errors="replace")

            x, y, w, h = qr.rect
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            # Standard-Overlay
            overlay = "QR erkannt"

            now = time.time()
            if data != last or (now - last_t) > cooldown:
                last, last_t = data, now

                # Nur bei Dokume-QR auswerten
                if is_dokume_url(data):
                    try:
                        info = parse_dokume_qr(data)
                        valid = is_valid(info["exp_timestamp"])
                        asyncio.run(send_info(info))

                        
                        # Terminal: NUR VALID/NOT VALID
                        print(VALID if valid else NOT_VALID)

                        # Overlay optional mit Namen
                        name = (info["first_name"] + " " + info["last_name"]).strip()
                        overlay = f"{VALID if valid else NOT_VALID} {name}".strip()

                    except Exception:
                        print(NOT_VALID)
                        overlay = NOT_VALID
                else:
                    # Nicht-Dokume-QR: ignorieren oder als NOT VALID werten (hier: ignorieren)
                    print("Inoffizieler")
                    

            cv2.putText(
                frame,
                overlay[:80],
                (x, max(0, y - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )

        cv2.imshow("QR", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

except KeyboardInterrupt:
    print("\nBeendet per Strg+C")

finally:
    cap.release()
    cv2.destroyAllWindows()
