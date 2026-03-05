# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

import cv2
import numpy as np
import logging
from wsclient import WebSocketClient, WeightClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

URL = "ws://localhost:8765"

DECODE_W, DECODE_H = 80, 140
MIN_DIGITS, MAX_DIGITS = 3, 5

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
        (0            , int(h * 0.20), int(w * 0.50), int(h * 0.40)),  # tl
        (int(w * 0.50), int(h * 0.20), w            , int(h * 0.40)),  # tr
        (int(w * 0.30), int(h * 0.40), int(w * 0.70), int(h * 0.62)),  # mid
        (0            , int(h * 0.60), int(w * 0.50), int(h * 0.80)),  # bl
        (int(w * 0.50), int(h * 0.60), w            , int(h * 0.80)),  # br
        (0            , int(h * 0.80), w            , h            ),  # bottom
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



def auto_digit_boxes_from_mask(mask, min_w_over_h=0.6, pad_x=0.10, pad_y=0.15):
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
    for (x, y, w_raw, h_raw) in raw:
        w = w_raw * (1.0 + pad_x)
        h = h_raw * (1.0 + pad_y)

        if (w / h) < min_w_over_h:
            w = min_w_over_h * h

        w = int(round(w))
        h = int(round(h))

        anchor_x = x + w_raw          
        anchor_y = y + h_raw / 2.0

        shift_x = int(round(w * 0.05))

        x1 = int(round(anchor_x - w + shift_x))
        y1 = int(round(anchor_y - h / 2.0))

        boxes.append((x1, y1, w, h))

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
        return None

    return "".join(str(d) for d in digits)



def _decode_current_weight(frame, last_boxes):
    mask = red_mask(frame)

    boxes = auto_digit_boxes_from_mask(mask)
    if boxes is None:
        boxes = last_boxes
        if boxes is None:
            logger.error("Auto Detection failed, no boxes found")
            return None, last_boxes
    else:
        last_boxes = boxes

    text= decode_from_fixed_boxes(mask, boxes)

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

    cv2.imshow("debug", dbg)

    return text, last_boxes


async def main(cam_index: int = 0):
    cap = cv2.VideoCapture(cam_index)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    cap.set(cv2.CAP_PROP_EXPOSURE, -10)
    if not cap.isOpened():
        raise RuntimeError("Webcam cannot be opened.")

    last_boxes = None

    ws = WebSocketClient(URL)
    await ws.connect()
    logger.info("WS connected: %s", URL)

    def weight_provider():
        nonlocal last_boxes

        text, last_boxes = _decode_current_weight(frame, last_boxes)
        if text is None:
            return None
        
        return text

    weight_client = WeightClient(ws, weight_provider)

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                return None

            cv2.imshow("live", frame)
            cv2.waitKey(1)

            try:
                msg = await asyncio.wait_for(ws.recv_json(), timeout=0.01)
            except asyncio.TimeoutError:
                continue

            await weight_client.handle_message(msg)

    finally:
        await ws.close()
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())