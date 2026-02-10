import cv2
import numpy as np

# ---------- Kamera öffnen ----------
cap = cv2.VideoCapture(0)  # ggf. 0/1/2
cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # kann je nach Cam variieren
cap.set(cv2.CAP_PROP_EXPOSURE, -6)         # ggf. -4 bis -10 testen

if not cap.isOpened():
    raise RuntimeError("Webcam konnte nicht geöffnet werden.")

roi = None  # (x, y, w, h)
digit_boxes_fixed = None  # Liste von 4 Boxes: [(x,y,w,h), ...] im ROI-Koordinatensystem
DIG_W, DIG_H = 80, 140    # feste Digit-Normalisierung fürs Decoding


def select_roi(frame):
    r = cv2.selectROI("ROI auswählen (ENTER=OK, ESC=abbrechen)", frame, fromCenter=False, showCrosshair=True)
    cv2.destroyWindow("ROI auswählen (ENTER=OK, ESC=abbrechen)")
    x, y, w, h = map(int, r)
    print("ROI gewählt:", (x, y, w, h))
    if w == 0 or h == 0:
        print("ROI ungültig (w/h = 0) -> bitte Rechteck ziehen und ENTER.")
        return None
    return (x, y, w, h)

def red_mask(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    lower1 = np.array([0, 120, 80]);   upper1 = np.array([10, 255, 255])
    lower2 = np.array([170, 120, 80]); upper2 = np.array([180, 255, 255])

    m1 = cv2.inRange(hsv, lower1, upper1)
    m2 = cv2.inRange(hsv, lower2, upper2)
    mask = cv2.bitwise_or(m1, m2)

        # Rauschen reduzieren / Segmente füllen (stärker, damit eine Ziffer 1 Kontur bleibt)
        # Segmente stärker verbinden, damit z.B. "8" nicht in 2 Konturen zerfällt
    kernel_close = np.ones((7, 7), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close, iterations=2)
    # optional: leicht verdicken
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
    # bin_digit muss schon ein Binary-Bild sein (0/255)
    if bin_digit is None or bin_digit.size == 0:
        return None

    h, w = bin_digit.shape[:2]
    if h < 20 or w < 10:
        return None

    # Rand weg
    pad_x = int(w * 0.08)
    pad_y = int(h * 0.08)
    img = bin_digit[pad_y:h-pad_y, pad_x:w-pad_x]
    if img.size == 0:
        return None

    h, w = img.shape[:2]

    regions = [
        (0,           int(h*0.00), w,            int(h*0.20)),  # top
        (0,           int(h*0.15), int(w*0.35),  int(h*0.55)),  # tl
        (int(w*0.65), int(h*0.15), w,            int(h*0.55)),  # tr
        (0,           int(h*0.40), w,            int(h*0.62)),  # mid
        (0,           int(h*0.55), int(w*0.35),  int(h*0.95)),  # bl
        (int(w*0.65), int(h*0.55), w,            int(h*0.95)),  # br
        (0,           int(h*0.80), w,            h),            # bottom
    ]

    on = []
    for (x1, y1, x2, y2) in regions:
        seg = img[y1:y2, x1:x2]
        if seg.size == 0:
            on.append(0)
            continue
        fill = cv2.countNonZero(seg) / float(seg.size)

        thr = 0.22  # globaler Grundwert (war 0.18)
        # TR (Index 2) und BR (Index 5) etwas strenger, damit Reflexe nicht als "an" zählen
        if len(on) in (2, 5):
            thr = 0.26
        elif len(on) == 3:
            thr = 0.50

        on.append(1 if fill > thr else 0)


    return SEG2DIG.get(tuple(on), None)


def calibrate_fixed_boxes(crop_bgr, num_digits=4):
    """
    Klick num_digits mal auf die Ziffern (von links nach rechts).
    Daraus wird eine feste Box-Größe abgeleitet.
    """
    pts = []
    show = crop_bgr.copy()

    def on_mouse(event, x, y, flags, param):
        nonlocal show
        if event == cv2.EVENT_LBUTTONDOWN:
            pts.append((x, y))
            cv2.circle(show, (x, y), 5, (0, 255, 0), -1)
            cv2.putText(show, str(len(pts)), (x+8, y-8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)

    win = "Kalibrierung: auf 4 Ziffern klicken (links->rechts), ESC=abbrechen"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)

    while True:
        cv2.imshow(win, show)
        k = cv2.waitKey(20) & 0xFF
        if k == 27:  # ESC
            cv2.destroyWindow(win)
            return None
        if len(pts) == num_digits:
            cv2.destroyWindow(win)
            break

    # sortiere nach x (links->rechts)
    pts = sorted(pts, key=lambda p: p[0])

    # Box-Größe schätzen: Abstand zwischen Zentren
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    # typische Digit-Breite ~ 0.75 * Abstand zwischen Zentren
    if num_digits >= 2:
        dx = np.median([xs[i+1]-xs[i] for i in range(num_digits-1)])
    else:
        dx = 60

    box_w = int(max(30, dx * 0.85))
    box_h = int(max(60, box_w * 1.7))  # 7-Segment eher hoch

    boxes = []
    for (cx, cy) in pts:
        x1 = int(cx - box_w/2)
        y1 = int(cy - box_h/2)
        boxes.append((x1, y1, box_w, box_h))

    return boxes


def decode_from_fixed_boxes(mask, boxes):
    digits = []
    for (x, y, w, h) in boxes:
        # Clip in Grenzen
        x1 = max(0, x); y1 = max(0, y)
        x2 = min(mask.shape[1], x + w)
        y2 = min(mask.shape[0], y + h)

        dimg = mask[y1:y2, x1:x2]
        if dimg.size == 0:
            digits.append(None)
            continue

        dimg = cv2.resize(dimg, (DIG_W, DIG_H), interpolation=cv2.INTER_NEAREST)
        digits.append(decode_7seg_digit(dimg))

    if any(d is None for d in digits):
        return None, digits
    if len(digits) == 4:
        return f"{digits[0]}{digits[1]}:{digits[2]}{digits[3]}", digits
    return "".join(str(d) for d in digits), digits


def split_wide_box(mask, box):
    """Splittet eine zu breite Box in 2 Boxes anhand eines vertikalen 'Tals'."""
    x, y, w, h = box
    roi = mask[y:y+h, x:x+w]
    if roi.size == 0:
        return [box]

    # Vertikale Projektion (Summe weißer Pixel pro Spalte)
    col_sum = np.sum(roi > 0, axis=0).astype(np.float32)

    # In der Mitte nach dem besten "Tal" suchen (wo am wenigsten Pixel sind)
    left = int(w * 0.35)
    right = int(w * 0.65)
    if right <= left:
        return [box]

    valley = np.argmin(col_sum[left:right]) + left

    # Nicht zu nah am Rand splitten
    if valley < int(w * 0.25) or valley > int(w * 0.75):
        return [box]

    box1 = (x, y, valley, h)
    box2 = (x + valley, y, w - valley, h)
    return [box1, box2]

def merge_boxes_close(boxes):
    if not boxes:
        return boxes
    boxes = sorted(boxes, key=lambda b: b[0])
    merged = []

    for (x, y, w, h) in boxes:
        x2, y2 = x + w, y + h
        if not merged:
            merged.append((x, y, w, h))
            continue

        mx, my, mw, mh = merged[-1]
        mx2, my2 = mx + mw, my + mh

        # Wenn Boxen horizontal sehr nah sind und ähnlich hoch -> zusammenführen
        gap = x - mx2
        h_similar = (min(h, mh) / max(h, mh)) > 0.6

        if gap < 12 and h_similar:
            nx1, ny1 = min(x, mx), min(y, my)
            nx2, ny2 = max(x2, mx2), max(y2, my2)
            merged[-1] = (nx1, ny1, nx2 - nx1, ny2 - ny1)
        else:
            merged.append((x, y, w, h))

    return merged


def merge_boxes_same_digit(boxes):
    """Merged Boxen, die sich stark in X überlappen (typisch: Ziffer zerfällt in oben/unten)."""
    if not boxes:
        return boxes

    boxes = sorted(boxes, key=lambda b: (b[0], b[1]))
    merged = []

    for (x, y, w, h) in boxes:
        x2, y2 = x + w, y + h
        placed = False

        for i, (mx, my, mw, mh) in enumerate(merged):
            mx2, my2 = mx + mw, my + mh

            # X-Overlap Verhältnis
            overlap = max(0, min(x2, mx2) - max(x, mx))
            min_w = min(w, mw)
            x_overlap_ratio = overlap / (min_w + 1e-6)

            # wenn starkes X-Overlap -> gehört sehr wahrscheinlich zur selben Ziffer
            if x_overlap_ratio > 0.6:
                nx1, ny1 = min(x, mx), min(y, my)
                nx2, ny2 = max(x2, mx2), max(y2, my2)
                merged[i] = (nx1, ny1, nx2 - nx1, ny2 - ny1)
                placed = True
                break

        if not placed:
            merged.append((x, y, w, h))

    return sorted(merged, key=lambda b: b[0])



def extract_and_decode(mask):
    """
    mask: binäre Maske (0/255) im ROI
    -> erkennt Ziffern, decodiert, gibt String zurück
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    raw = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if area < 350:
            continue
        raw.append((x, y, w, h))

    if not raw:
        return None, []

    # links->rechts sortieren
    raw.sort(key=lambda b: b[0])

    # Höhe-Median (hilft beim Herausfiltern von Doppelpunkt/Artefakten)
    heights = np.array([h for (_, _, _, h) in raw], dtype=np.float32)
    med_h = float(np.median(heights))

    # Erstmal nur "digit-ähnliche" Kandidaten behalten
    candidates = []
    for (x, y, w, h) in raw:
        # Doppelpunkt/kleine Artefakte sind deutlich kleiner
        if h < 0.65 * med_h:
            continue
        # sehr dünne Striche (Artefakte) raus
        if w < 0.08 * h:
            continue
        candidates.append((x, y, w, h))

    if not candidates:
        return None, []

    # Median-Breite für "zu breite Box = vermutlich 2 Ziffern zusammen"
    widths = np.array([w for (_, _, w, _) in candidates], dtype=np.float32)
    med_w = float(np.median(widths))

    # Zu breite Boxes splitten
    digit_boxes = []
    for b in candidates:
        x, y, w, h = b
        if w > 1.55 * med_w:  # Schwelle: Box ist deutlich breiter als normal
            digit_boxes.extend(split_wide_box(mask, b))
        else:
            digit_boxes.append(b)

    # wieder sortieren
    digit_boxes.sort(key=lambda b: b[0])
    digit_boxes = merge_boxes_same_digit(digit_boxes)
    digit_boxes = merge_boxes_close(digit_boxes)
    digits = []
    for (x, y, w, h) in digit_boxes:
        dimg = mask[y:y+h, x:x+w]

        # Ein bisschen "padding" als schwarzer Rand, damit Segmente nicht abgeschnitten werden
        pad = 15
        dimg = cv2.copyMakeBorder(dimg, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)

        dimg = cv2.resize(dimg, (80, 140), interpolation=cv2.INTER_NEAREST)
        val = decode_7seg_digit(dimg)
        digits.append(val)

    if any(d is None for d in digits) or len(digits) == 0:
        return None, digit_boxes

    # Uhr: 4 Ziffern -> HH:MM
    if len(digits) == 4:
        s = f"{digits[0]}{digits[1]}:{digits[2]}{digits[3]}"
    else:
        s = "".join(str(d) for d in digits)

    return s, digit_boxes


print("Tasten: r = ROI wählen | s = Snapshot+Auswertung | q = quit")

while True:
    ok, frame = cap.read()
    if not ok:
        break

    disp = frame.copy()

    if roi is not None:
        x, y, w, h = roi
        cv2.rectangle(disp, (x, y), (x+w, y+h), (0, 255, 0), 2)

    cv2.imshow("live", disp)

    key = cv2.waitKey(1) & 0xFF

    if key == ord('r'):
        roi = select_roi(frame)

    elif key == ord('c'):
        if roi is None:
            print("Bitte zuerst ROI mit 'r' auswählen.")
            continue

        x, y, w, h = roi
        crop = frame[y:y+h, x:x+w]

        boxes = calibrate_fixed_boxes(crop, num_digits=4)
        if boxes is None:
            print("Kalibrierung abgebrochen.")
        else:
            digit_boxes_fixed = boxes
            print("Feste Digit-Boxes gesetzt:", digit_boxes_fixed)


    elif key == ord('s'):
        if roi is None:
            print("Bitte zuerst ROI mit 'r' auswählen.")
            continue

        x, y, w, h = roi
        crop = frame[y:y+h, x:x+w]
        mask = red_mask(crop)

        if digit_boxes_fixed is None:
            print("Bitte zuerst mit 'c' kalibrieren (feste Boxen setzen).")
            continue

        text, digits = decode_from_fixed_boxes(mask, digit_boxes_fixed)


        # Debug-Fenster (optional aber hilfreich)
        dbg = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        for (bx, by, bw, bh) in digit_boxes_fixed:
            cv2.rectangle(dbg, (bx, by), (bx+bw, by+bh), (0, 255, 0), 1)
        cv2.imshow("mask (ROI)", mask)
        cv2.imshow("debug (ROI)", dbg)

        if text is None:
            print("Konnte Zahl nicht sicher decodieren. (Tipp: ROI enger, Kamera ruhiger, ggf. Schwellwert anpassen)")
        else:
            print("Erkannt:", text)

    elif key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
