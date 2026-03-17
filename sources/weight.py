# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

import cv2
import numpy as np
import logging
import tkinter as tk
import asyncio
import time
import websockets
from wsclient import WebSocketClient, WeightClient, WebSocketDisconnected
from list_available_cameras import list_available_cameras

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

URL = "ws://localhost:8765"
RECONNECT_DELAY_S = 2.0

DECODE_W, DECODE_H = 80, 140
MIN_DIGITS, MAX_DIGITS = 3, 5


def _show_camera_in_use_dialog():
    root = tk.Tk()
    root.withdraw()

    popup = tk.Toplevel(root)
    popup.title("Kamera")
    popup.attributes("-topmost", True)
    popup.resizable(False, False)
    tk.Label(
        popup,
        text="Kamera wird bereits von einem anderen Programm verwendet",
        wraplength=320,
        justify="center",
    ).pack(padx=20, pady=14)
    tk.Button(popup, text="OK", width=10, command=popup.destroy).pack(pady=(0, 12))

    popup.update_idletasks()
    x = (popup.winfo_screenwidth() - popup.winfo_width()) // 2
    y = (popup.winfo_screenheight() - popup.winfo_height()) // 2
    popup.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    popup.focus_force()
    popup.wait_window()

    try:
        root.destroy()
    except tk.TclError:
        pass


def _camera_name_for_index(camera_index: int) -> str:
    for idx, name in list_available_cameras():
        if idx == camera_index:
            return name
    return f"Kamera {camera_index}"


def _show_camera_probe_dialog():
    root = tk.Tk()
    root.withdraw()

    popup = tk.Toplevel(root)
    popup.title("Kamera")
    popup.attributes("-topmost", True)
    popup.resizable(False, False)
    popup.protocol("WM_DELETE_WINDOW", lambda: None)
    tk.Label(
        popup,
        text="Überprüfen der Kamera, bitte warten...",
        padx=28,
        pady=18,
    ).pack()

    popup.update_idletasks()
    x = (popup.winfo_screenwidth() - popup.winfo_width()) // 2
    y = (popup.winfo_screenheight() - popup.winfo_height()) // 2
    popup.geometry(f"200x100+{max(x, 0)}+{max(y, 0)}")
    popup.focus_force()
    popup.grab_set()
    popup.update()
    return root, popup


def _close_camera_probe_dialog(root, popup):
    try:
        popup.grab_release()
    except Exception:
        pass
    try:
        popup.destroy()
    except tk.TclError:
        pass
    try:
        root.destroy()
    except tk.TclError:
        pass


def _show_camera_probe_success_dialog(camera_name: str):
    root = tk.Tk()
    root.withdraw()

    popup = tk.Toplevel(root)
    popup.title("Kamera")
    popup.attributes("-topmost", True)
    popup.resizable(False, False)
    tk.Label(
        popup,
        text=f"{camera_name}\nerfolgreich eingesetzt fur Waage",
        wraplength=340,
        justify="center",
    ).pack(padx=20, pady=14)
    tk.Button(popup, text="OK", width=10, command=popup.destroy).pack(pady=(0, 12))

    popup.update_idletasks()
    x = (popup.winfo_screenwidth() - popup.winfo_width()) // 2
    y = (popup.winfo_screenheight() - popup.winfo_height()) // 2
    popup.geometry(f"200x100+{max(x, 0)}+{max(y, 0)}")
    popup.focus_force()
    popup.wait_window()

    try:
        root.destroy()
    except tk.TclError:
        pass


def _camera_frame_looks_blocked(frame) -> bool:
    if frame is None:
        return True
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mean, stddev = cv2.meanStdDev(gray)
    except Exception:
        return True

    brightness = float(mean[0][0])
    contrast = float(stddev[0][0])
    return brightness <= 3.0 or contrast <= 1.0


def _probe_selected_camera(camera_index: int) -> bool:
    probe_root, probe_popup = _show_camera_probe_dialog()
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        logger.warning("Camera index %s is not opened during probe", camera_index)
        cap.release()
        _close_camera_probe_dialog(probe_root, probe_popup)
        return False

    try:
        time.sleep(0.3)
        good_frames = 0
        for _ in range(10):
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            if _camera_frame_looks_blocked(frame):
                continue
            good_frames += 1
            if good_frames >= 2:
                return True

        logger.warning(
            "Camera index %s only returned %s good frames during probe",
            camera_index,
            good_frames,
        )
        return False
    finally:
        cap.release()
        _close_camera_probe_dialog(probe_root, probe_popup)


def _camera_capture_is_usable(cap, camera_index: int) -> bool:
    for _ in range(5):
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        if _camera_frame_looks_blocked(frame):
            logger.warning("Camera index %s returned blocked/dark frames", camera_index)
            return False
        return True

    logger.warning("Camera index %s did not return readable frames", camera_index)
    return False


def select_camera_index() -> int:
    cameras = list_available_cameras()
    if not cameras:
        raise RuntimeError("No Camera found")

    root = tk.Tk()
    root.withdraw()

    popup_w = 360
    popup_h = 300
    result = {"index": None}

    popup = tk.Toplevel()
    popup.title("Kamera Für die Waage auswählen")
    popup.geometry(f"{popup_w}x{popup_h}")
    popup.resizable(False, False)
    popup.attributes("-topmost", True)
    popup.protocol("WM_DELETE_WINDOW", popup.destroy)

    popup.update_idletasks()
    x = (popup.winfo_screenwidth() - popup_w) // 2
    y = (popup.winfo_screenheight() - popup_h) // 2
    popup.geometry(f"{popup_w}x{popup_h}+{max(x, 0)}+{max(y, 0)}")

    frame = tk.Frame(popup, padx=12, pady=12)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text="Verfügbare Kameras:").pack(anchor="w", pady=(0, 8))

    listbox = tk.Listbox(frame, height=10)
    for cam_idx, cam_name in cameras:
        listbox.insert(tk.END, f"[{cam_idx}] {cam_name}")
    listbox.pack(fill="both", expand=True)
    listbox.selection_set(0)

    def choose():
        sel = listbox.curselection()
        if not sel:
            return
        result["index"] = cameras[sel[0]][0]
        popup.destroy()

    btn_row = tk.Frame(frame)
    btn_row.pack(pady=(10, 0))
    tk.Button(btn_row, text="Öffnen", width=14, command=choose).pack(side=tk.LEFT, padx=6)
    tk.Button(btn_row, text="Abbrechen", width=14, command=popup.destroy).pack(side=tk.LEFT, padx=6)

    popup.focus_force()
    popup.wait_window()

    try:
        root.destroy()
    except tk.TclError:
        pass

    if result["index"] is None:
        raise RuntimeError("Kameraauswahl abgebrochen.")
    return result["index"]


_select_camera_index_once = select_camera_index


def select_camera_index() -> int:
    while True:
        camera_index = _select_camera_index_once()
        if _probe_selected_camera(camera_index):
            _show_camera_probe_success_dialog(_camera_name_for_index(camera_index))
            return camera_index
        _show_camera_in_use_dialog()

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


def _build_debug_image(mask, boxes):
    dbg = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

    if not boxes:
        return dbg

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

    return dbg


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

    text = decode_from_fixed_boxes(mask, boxes)

    return text, last_boxes


def _show_detection_error_dialog(cap, initial_frame, last_boxes):
    root = tk.Tk()
    root.withdraw()

    popup_w = 460
    popup_h = 180
    state = {"retry_requested": False}
    current_frame = initial_frame
    updated_boxes = last_boxes

    popup = tk.Toplevel(root)
    popup.title("Fehler")
    popup.geometry(f"{popup_w}x{popup_h}")
    popup.resizable(False, False)
    popup.attributes("-topmost", True)

    def close(event=None):
        try:
            popup.destroy()
        except tk.TclError:
            pass

        try:
            root.destroy()
        except tk.TclError:
            pass

        state["retry_requested"] = False
        state["cancel"] = True

    popup.protocol("WM_DELETE_WINDOW", close)
    popup.bind("<Escape>", close)

    popup.update_idletasks()
    x = (popup.winfo_screenwidth() - popup_w) // 2
    y = 40
    popup.geometry(f"{popup_w}x{popup_h}+{max(x, 0)}+{max(y, 0)}")

    frame = tk.Frame(popup, padx=16, pady=16)
    frame.pack(fill="both", expand=True)

    tk.Label(
        frame,
        text="Fehler: Bitte Kamera anpassen",
        font=("Arial", 16, "bold"),
        justify="center",
    ).pack(pady=(8, 16))

    def request_retry():
        state["retry_requested"] = True

    tk.Button(frame, text="OK", width=12, command=request_retry).pack()

    try:
        while True:
            if state.get("cancel"):
                break
            
            ok, next_frame = cap.read()
            if ok and next_frame is not None:
                current_frame = next_frame

            mask = red_mask(current_frame)
            boxes = auto_digit_boxes_from_mask(mask)
            dbg = _build_debug_image(mask, boxes)

            cv2.imshow("live", current_frame)
            cv2.imshow("debug", dbg)

            cv2.moveWindow("live", 50, 250)
            cv2.moveWindow("debug", 700, 250)
            
            cv2.waitKey(1)

            root.update_idletasks()
            root.update()

            if not state["retry_requested"]:
                continue

            state["retry_requested"] = False
            if boxes is None:
                logger.error("Auto Detection failed, no boxes found")
                continue

            text = decode_from_fixed_boxes(mask, boxes)
            if text is None:
                logger.error("Digit decode failed during manual retry")
                continue

            updated_boxes = boxes
            break


    finally:
        try:
            popup.destroy()
        except tk.TclError:
            pass
        try:
            root.destroy()
        except tk.TclError:
            pass
        try:
            cv2.destroyWindow("live")
        except cv2.error:
            pass
        try:
            cv2.destroyWindow("debug")
        except cv2.error:
            pass

    return updated_boxes


async def main(cam_index: int = 0):
    def open_camera(camera_index: int):
        opened_cap = cv2.VideoCapture(camera_index)
        opened_cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        opened_cap.set(cv2.CAP_PROP_EXPOSURE, -10)
        if not opened_cap.isOpened():
            opened_cap.release()
            raise RuntimeError("Webcam cannot be opened.")
        if not _camera_capture_is_usable(opened_cap, camera_index):
            opened_cap.release()
            raise RuntimeError("Camera is already in use.")
        return opened_cap

    while True:
        try:
            cap = open_camera(cam_index)
            break
        except RuntimeError as exc:
            logger.warning("Opening selected camera failed: %s", exc)
            _show_camera_in_use_dialog()
            cam_index = select_camera_index()

    last_boxes = None

    ws = WebSocketClient(URL)

    async def connect_with_retry():
        while True:
            try:
                await ws.connect()
                logger.info("WS connected: %s", URL)
                return
            except (OSError, websockets.WebSocketException) as exc:
                logger.warning("WS connect failed, retry in %.1fs: %s", RECONNECT_DELAY_S, exc)
                await asyncio.sleep(RECONNECT_DELAY_S)

    def weight_provider():
        nonlocal last_boxes

        text, last_boxes = _decode_current_weight(frame, last_boxes)
        if text is None:
            last_boxes = _show_detection_error_dialog(cap, frame, last_boxes)
            return None
        
        return text

    weight_client = WeightClient(ws, weight_provider)

    try:
        await connect_with_retry()
        await weight_client.register()
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                return None

            try:
                msg = await asyncio.wait_for(ws.recv_json(), timeout=0.01)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnected as exc:
                logger.warning("WS recv failed, reconnecting: %s", exc)
                await connect_with_retry()
                await weight_client.register()
                continue

            if msg.get("type") == "OPEN_CAMERA_SELECTION":
                try:
                    selected_camera = select_camera_index()
                except RuntimeError:
                    continue

                try:
                    new_cap = open_camera(selected_camera)
                except RuntimeError as exc:
                    logger.warning("Opening selected camera failed: %s", exc)
                    _show_camera_in_use_dialog()
                    continue

                cap.release()
                cap = new_cap
                cam_index = selected_camera
                last_boxes = None
                continue

            try:
                await weight_client.handle_message(msg)
            except WebSocketDisconnected as exc:
                logger.warning("WS send failed, reconnecting: %s", exc)
                await connect_with_retry()
                await weight_client.register()

    finally:
        await ws.close()
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    selected_camera = select_camera_index()
    asyncio.run(main(selected_camera))
