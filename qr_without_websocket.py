# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
#
# SPDX-License-Identifier: CC0-1.0

import cv2
from pyzbar.pyzbar import decode
import time
import base64
import json
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from zoneinfo import ZoneInfo

CAM_INDEX = 0

# ----------------- Dokume Parser -----------------

def base64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)

def parse_dokume_qr(url: str) -> dict:
    """
    Parst Dokume QR-URL:
    https://qr.dokume.net?d=l&i=...&s=HEADER.PAYLOAD.SIGNATURE
    Gibt wichtige Felder zurück (ohne Signaturprüfung).
    """
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    if "s" not in query:
        raise ValueError("Kein JWT ('s' Parameter) in der URL gefunden.")

    jwt_token = query["s"][0]
    parts = jwt_token.split(".")
    if len(parts) != 3:
        raise ValueError("Ungültiges JWT-Format (erwarte 3 Teile).")

    header_b64, payload_b64, _sig = parts

    payload = json.loads(base64url_decode(payload_b64))

    exp = payload.get("exp")
    expires_datetime = None
    expires_date = None
    if exp is not None:
        dt = datetime.fromtimestamp(int(exp), tz=ZoneInfo("Europe/Berlin"))
        expires_datetime = dt
        expires_date = dt.date()

    return {
        "issuer": payload.get("iss"),
        "uid": payload.get("UID"),
        "first_name": payload.get("FN"),
        "last_name": payload.get("LN"),
        "birth_date": payload.get("DOB"),
        "license_type": payload.get("LTN"),
        "license_code": payload.get("NO"),
        "expires_datetime": expires_datetime,
        "expires_date": expires_date,
        "raw_payload": payload
    }

def is_expired(expires_datetime: datetime) -> bool:
    if expires_datetime is None:
        raise ValueError("Kein Ablaufdatum vorhanden.")
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    return now > expires_datetime

def is_dokume_url(s: str) -> bool:
    # genügt für eure Fälle; wenn du willst, kann man das strenger machen
    return s.startswith("https://qr.dokume.net") or s.startswith("http://qr.dokume.net")

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

        qrs = decode(frame)
        for qr in qrs:
            data = qr.data.decode("utf-8", errors="replace")

            x, y, w, h = qr.rect
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            now = time.time()
            if data != last or (now - last_t) > cooldown:
                last, last_t = data, now

                print("\nQR erkannt:", data)

                # --- Dokume-QR auswerten ---
                if is_dokume_url(data):
                    try:
                        info = parse_dokume_qr(data)

                        fn = info.get("first_name") or ""
                        ln = info.get("last_name") or ""
                        ltype = info.get("license_type") or ""
                        exp_dt = info.get("expires_datetime")
                        exp_date = info.get("expires_date")

                        expired = is_expired(exp_dt) if exp_dt else None

                        print(f"Name: {fn} {ln}".strip())
                        print(f"Lizenz: {ltype}")
                        print(f"Ablauf (Berlin): {exp_dt}")
                        if expired is True:
                            print("Status: ❌ ABGELAUFEN")
                        elif expired is False:
                            print("Status: ✅ NICHT abgelaufen")
                        else:
                            print("Status: (kein Ablaufdatum im Token)")

                    except Exception as e:
                        print("Dokume-Parse Fehler:", e)
                else:
                    print("Hinweis: Kein Dokume-QR (oder anderes Format).")

            # --- Overlay Text im Bild (kurz) ---
            overlay = "QR erkannt"
            if is_dokume_url(data):
                try:
                    info = parse_dokume_qr(data)
                    fn = info.get("first_name") or ""
                    ln = info.get("last_name") or ""
                    exp_date = info.get("expires_date")
                    exp_dt = info.get("expires_datetime")
                    expired = is_expired(exp_dt) if exp_dt else None

                    status_txt = "OK" if expired is False else ("ABGELAUFEN" if expired is True else "UNKLAR")
                    overlay = f"{fn} {ln} | bis {exp_date} | {status_txt}".strip()
                except Exception:
                    overlay = "Dokume QR (Parse Fehler)"

            cv2.putText(
                frame,
                overlay[:80],  # sicherheitshalber begrenzen
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