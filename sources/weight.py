# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

# =========================
# Build WebSocket Connection
# =========================
import asyncio
import websockets
import json

import cv2
import numpy as np

URL = "ws://localhost:8765"

async def send_weight(weight):
    async with websockets.connect(URL) as websocket:
        print("Connected to server")

        message = {
                "type": "weight",
                "weight": weight
        }

        await websocket.send(json.dumps(message))
        print("Sent: ", message)

# ---------------------------------
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
cap.set(cv2.CAP_PROP_EXPOSURE, -10)

if not cap.isOpened():
    raise RuntimeError("Webcam konnte nicht geöffnet werden.")

DECODE_W, DECODE_H = 80, 140  
BOX_W, BOX_H = 100, 160
MIN_DIGITS, MAX_DIGITS = 3, 5    

last_boxes = None


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
    (1,1,1,0,1,1,1): 0,
    (0,0,1,0,0,1,0): 1,
    (1,0,1,1,1,0,1): 2,
    (1,0,1,1,0,1,1): 3,
    (0,1,1,1,0,1,0): 4,
    (1,1,0,1,0,1,1): 5,
    (1,1,0,1,1,1,1): 6,
    (1,0,1,0,0,1,0): 7,
    (1,1,1,1,1,1,1): 8,
    (1,1,1,1,0,1,1): 9,
}

def decode_7seg_digit(bin_digit):
    if bin_digit is None or bin_digit.size == 0:
        return None

    h, w = bin_digit.shape[:2]
    if h < 20 or w < 10:
        return None

    img = bin_digit

    regions = [
        (int(w*0.30), int(h*0.00), int(w*0.70),    int(h*0.20)),   # top
        (0,           int(h*0.20), int(w*0.50),  int(h*0.40)),  # tl
        (int(w*0.50), int(h*0.20), w,            int(h*0.40)),  # tr
        (int(w*0.30), int(h*0.40), int(w*0.70),  int(h*0.62)),   # mid
        (0,           int(h*0.60), int(w*0.50),  int(h*0.80)),   # bl
        (int(w*0.50), int(h*0.60), w,            int(h*0.80)),   # br
        (0,           int(h*0.80), w,            h),             # bottom
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

        shift_x = int(round(BOX_W*0.05))
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


print("Tasten: s = Snapshot+Auswertung (AUTO boxes) | q = quit")

while True:
    ok, frame = cap.read()
    if not ok or frame is None:
        break

    disp = frame.copy()
    cv2.imshow("live", disp)

    key = cv2.waitKey(1) & 0xFF

    if key == ord('s'):
        mask = red_mask(frame)

        boxes = auto_digit_boxes_from_mask(mask)
        if boxes is None:
            if last_boxes is not None:
                boxes = last_boxes
            else:
                print("Auto-Detection fehlgeschlagen (weniger als 3 Ziffern gefunden).")
                continue
        else:
            last_boxes = boxes

        text, digits = decode_from_fixed_boxes(mask, boxes)

        # Debug: show mask + boxes + segment regions
        dbg = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

        for (bx, by, bw, bh) in boxes:
            cv2.rectangle(dbg, (bx, by), (bx+bw, by+bh), (0, 255, 0), 1)

            h = bh
            w = bw
            xL = int(w * 0.30)
            xR = int(w * 0.70)

            regions = [
                (xL,          int(h*0.00), xR,           int(h*0.20)),  # top
                (0,           int(h*0.20), int(w*0.50),  int(h*0.40)),  # tl
                (int(w*0.50), int(h*0.20), w,            int(h*0.40)),  # tr
                (xL,          int(h*0.40), xR,           int(h*0.62)),  # mid
                (0,           int(h*0.60), int(w*0.50),  int(h*0.80)),   # bl
                (int(w*0.50), int(h*0.60), w,            int(h*0.80)),   # br
                (xL,          int(h*0.80), xR,           h),            # bottom
            ]

            for (x1, y1, x2, y2) in regions:
                cv2.rectangle(dbg, (bx + x1, by + y1), (bx + x2, by + y2), (255, 0, 0), 1)

        cv2.imshow("debug (FULL)", dbg)

        if text is None:
            failed = [i for i, d in enumerate(digits) if d is None]
            failed_human = [i+1 for i in failed]
            print(f"Konnte nicht sicher decodieren. Fehler bei Ziffer(n): {failed_human} | digits={digits}")
        else:
            asyncio.run(send_weight(text))

    elif key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
