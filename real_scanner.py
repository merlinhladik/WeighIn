# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
#
# SPDX-License-Identifier: CC0-1.0

import time
import base64
import json
import asyncio
import websockets
from urllib.parse import urlparse, parse_qs

import keyboard  # pip install keyboard

WS_URL = "ws://localhost:8765"
COOLDOWN_S = 1.0  # Spam verhindern

# ----------------- WebSocket Sender -----------------

async def send_info(info: dict):
    async with websockets.connect(WS_URL) as websocket:
        message = {"type": "qr", "info": info}
        await websocket.send(json.dumps(message))
        # optional: auf Antwort warten
        # resp = await websocket.recv()
        # print("Server:", resp)

def send_info_sync(info: dict):
    # einfacher Wrapper, damit wir in normalem Code senden können
    asyncio.run(send_info(info))

# ----------------- Dokume Parsing -----------------

def base64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)

def is_dokume_url(s: str) -> bool:
    return s.startswith("https://qr.dokume.net") or s.startswith("http://qr.dokume.net")

def parse_dokume_qr(url: str) -> dict:
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
        "birth_date": payload.get("DOB") or "",
        "exp_timestamp": int(exp),
        "uid": payload.get("UID") or "",
    }

def is_valid(exp_timestamp: int) -> bool:
    # reiner Zahlenvergleich, keine Zeitzonen/datetime
    return int(time.time()) <= int(exp_timestamp)

# ----------------- HID Scanner Reader (Keyboard) -----------------

def read_scanner_lines():
    """
    Generator: liefert jeweils eine komplette 'Zeile' vom Scanner.
    Scanner sendet typischerweise ENTER am Ende.
    ESC beendet.
    """
    print("Scanner-Modus aktiv.")
    print("- Scanne einen Code (Scanner tippt + ENTER)")
    print("- ESC beendet\n")

    buffer = []
    while True:
        event = keyboard.read_event(suppress=False)

        if event.event_type != keyboard.KEY_DOWN:
            continue

        name = event.name

        if name == "esc":
            return  # Generator endet -> Programm endet

        if name == "enter":
            line = "".join(buffer).strip()
            buffer.clear()
            if line:
                yield line
            continue

        # Scanner sendet meist normale Zeichen
        # Sondertasten, shift etc. ignorieren wir
        if len(name) == 1:
            buffer.append(name)
        elif name == "space":
            buffer.append(" ")
        # alles andere ignorieren

# ----------------- Main -----------------

def main():
    last_value = None
    last_time = 0.0

    for scanned in read_scanner_lines():
        now = time.time()
        if scanned == last_value and (now - last_time) < COOLDOWN_S:
            continue
        last_value, last_time = scanned, now

        # Output zur Kontrolle
        # print("RAW:", scanned)

        if not is_dokume_url(scanned):
            print("NOT VALID | (kein Dokume QR)")
            continue

        try:
            info = parse_dokume_qr(scanned)
            valid = is_valid(info["exp_timestamp"])

            status = "VALID" if valid else "NOT VALID"
            name = f"{info['first_name']} {info['last_name']}".strip()

            print(f"{status} | {name} | DOB={info['birth_date']}")

            # an deinen Server schicken (immer schicken oder nur bei VALID)
            send_info_sync(info)

        except Exception as e:
            print(f"NOT VALID | (Parse Fehler: {e})")

if __name__ == "__main__":
    main()