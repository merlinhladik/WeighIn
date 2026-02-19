# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

# =========================
# Build WebSocket Connection
# =========================
import asyncio
import json

import cv2
import numpy as np
import websockets

URL = "ws://localhost:8765"

DECODE_W, DECODE_H = 80, 140
BOX_W, BOX_H = 100, 160
MIN_DIGITS, MAX_DIGITS = 3, 5


async def send_weight(weight, websocket=None):
    message = {"type": "weight", "weight": weight}
    if websocket is None:
        async with websockets.connect(URL) as socket:
            print("Connected to server")
            await socket.send(json.dumps(message))
    else:
        await websocket.send(json.dumps(message))
    print("Sent: ", message)



def red_mask(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    lower1 = np.array([0, 120, 80])
    upper1 = np.array([10, 255, 255])
    lower2 = np.array([170, 120, 80])
    upper2 = np.array([180, 255, 255])

    m1 = cv2.inRange(hsv, lower1, upper1)
    m2 = cv2.inRange(hsv, lower2, upper2)
    mask = cv2.bitwise_or(m1, m2)

    kernel_close = np.ones((7, 7), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close, iterations=2)
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)

    return mask


# 7-Segment Mapping: (top, top-left, top-right, mid, bottom-left, bottom-right, bottom)
SEG2DIG = {
    (1, 1, 1, 0, 1, 1, 1): 0,
    (0, 0, 1, 0, 0, 1, 0): 1,
    (1, 0, 1, 1, 1, 0, 1): 2,
    (1, 0, 1, 1, 0, 1, 1): 3,
    (0, 1, 1, 1, 0, 1, 0): 4,
    (1, 1, 0, 1, 0, 1, 1): 5,
    (1, 1, 0, 1, 1, 1, 1): 6,
    (1, 0, 1, 0, 0, 1, 0): 7,
    (1, 1, 1, 1, 1, 1, 1): 8,
    (1, 1, 1, 1, 0, 1, 1): 9,
}


def decode_7seg_digit(bin_digit):
    if bin_digit is None or bin_digit.size == 0:
        return None

    h, w = bin_digit.shape[:2]
    if h < 20 or w < 10:
        return None

    img = bin_digit

    regions = [
        (int(w * 0.30), int(h * 0.00), int(w * 0.70), int(h * 0.20)),  # top
        (0, int(h * 0.20), int(w * 0.50), int(h * 0.40)),  # tl
        (int(w * 0.50), int(h * 0.20), w, int(h * 0.40)),  # tr
        (int(w * 0.30), int(h * 0.40), int(w * 0.70), int(h * 0.62)),  # mid
        (0, int(h * 0.60), int(w * 0.50), int(h * 0.80)),  # bl
        (int(w * 0.50), int(h * 0.60), w, int(h * 0.80)),  # br
        (0, int(h * 0.80), w, h),  # bottom
    ]

    on = []
    for (x1, y1, x2, y2) in regions:
        seg = img[y1:y2, x1:x2]
        if seg.size == 0:
            on.append(0)
            continue
        fill = cv2.countNonZero(seg) / float(seg.size)
        thr = 0.15
        on.append(1 if fill > thr else 0)

    return SEG2DIG.get(tuple(on), None)



def auto_digit_boxes_from_mask(mask):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    raw = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        raw.append((x, y, w, h))

    if not raw or len(raw) < MIN_DIGITS:
        return None

    raw.sort(key=lambda b: b[0])

    if len(raw) > MAX_DIGITS:
        raw = raw[:MAX_DIGITS]

    boxes = []

    for (x, y, w, h) in raw:
        anchor_x = x + w
        anchor_y = y + h / 2.0

        shift_x = int(round(BOX_W * 0.05))
        x1 = int(round(anchor_x - BOX_W + shift_x))
        y1 = int(round(anchor_y - BOX_H / 2))

        boxes.append((x1, y1, BOX_W, BOX_H))

    return boxes



def decode_from_fixed_boxes(mask, boxes):
    digits = []
    for (x, y, w, h) in boxes:
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(mask.shape[1], x + w)
        y2 = min(mask.shape[0], y + h)

        dimg = mask[y1:y2, x1:x2]
        if dimg.size == 0:
            digits.append(None)
            continue

        dimg = cv2.resize(dimg, (DECODE_W, DECODE_H), interpolation=cv2.INTER_NEAREST)
        digits.append(decode_7seg_digit(dimg))

    if any(d is None for d in digits) or len(digits) == 0:
        return None, digits

    return "".join(str(d) for d in digits), digits



def _decode_current_weight(frame, last_boxes):
    mask = red_mask(frame)

    boxes = auto_digit_boxes_from_mask(mask)
    if boxes is None:
        boxes = last_boxes
        if boxes is None:
            print("Auto-Detection fehlgeschlagen (weniger als 3 Ziffern gefunden).")
            return None, None, last_boxes
    else:
        last_boxes = boxes

    text, digits = decode_from_fixed_boxes(mask, boxes)

    # Debug: show mask + boxes + segment regions
    dbg = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

    for (bx, by, bw, bh) in boxes:
        cv2.rectangle(dbg, (bx, by), (bx + bw, by + bh), (0, 255, 0), 1)

        h = bh
        w = bw
        x_l = int(w * 0.30)
        x_r = int(w * 0.70)

        regions = [
            (x_l, int(h * 0.00), x_r, int(h * 0.20)),  # top
            (0, int(h * 0.20), int(w * 0.50), int(h * 0.40)),  # tl
            (int(w * 0.50), int(h * 0.20), w, int(h * 0.40)),  # tr
            (x_l, int(h * 0.40), x_r, int(h * 0.62)),  # mid
            (0, int(h * 0.60), int(w * 0.50), int(h * 0.80)),  # bl
            (int(w * 0.50), int(h * 0.60), w, int(h * 0.80)),  # br
            (x_l, int(h * 0.80), x_r, h),  # bottom
        ]

        for (x1, y1, x2, y2) in regions:
            cv2.rectangle(dbg, (bx + x1, by + y1), (bx + x2, by + y2), (255, 0, 0), 1)

    cv2.imshow("debug (FULL)", dbg)

    return text, digits, last_boxes


async def _run_weight_scanner_loop(cap):
    last_boxes = None

    async with websockets.connect(URL) as websocket:
        print("Connected to server")
        print("Warte auf REQUEST_WEIGHT von der GUI. Taste q beendet.")

        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break

            cv2.imshow("live", frame.copy())
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break

            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=0.01)
            except asyncio.TimeoutError:
                continue
            except Exception as err:
                print(f"WebSocket Fehler: {err}")
                break

            try:
                payload = json.loads(raw)
            except Exception:
                continue

            if payload.get("type") != "REQUEST_WEIGHT":
                continue

            text, digits, last_boxes = _decode_current_weight(frame, last_boxes)
            if text is None:
                failed = [i for i, d in enumerate(digits or []) if d is None]
                failed_human = [i + 1 for i in failed]
                print(f"Konnte nicht sicher decodieren. Fehler bei Ziffer(n): {failed_human} | digits={digits}")
                continue

            await send_weight(text, websocket=websocket)


def run_weight_scanner(cam_index: int = 0):
    cap = cv2.VideoCapture(cam_index)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    cap.set(cv2.CAP_PROP_EXPOSURE, -10)

    if not cap.isOpened():
        raise RuntimeError("Webcam konnte nicht geoeffnet werden.")

    try:
        asyncio.run(_run_weight_scanner_loop(cap))
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    run_weight_scanner()
