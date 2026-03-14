# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

import threading
import base64
import json
import asyncio
import time
import tkinter as tk
from typing import Optional
from wsclient import WebSocketClient, QRClient, WebSocketDisconnected
import keyboard
import logging
import websockets
from list_available_cameras import list_available_cameras

try:
    import cv2
except Exception:
    cv2 = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

URL = "ws://localhost:8765"
COOLDOWN_S = 1.0
HOTKEY_DEBOUNCE_S = 0.35
SCAN_HINT = "Bitte den QR scannen und hier nichts eintippen"
QR_ERROR_TEXT = "Error: Qr kann nicht erkannt werden"
RECONNECT_DELAY_S = 2.0


def base64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)

def extract_payload_b64(scanned: str) -> str:
    s = scanned.strip()
    parts = s.split(".")
    return parts[0]

def parse_dokume_qr(url: str) -> dict:
    payload_b64 = extract_payload_b64(url)
    payload = json.loads(base64url_decode(payload_b64))

    fn = payload.get("FN")
    ln = payload.get("LN")
    dob = payload.get("DOB")
    birthyear = dob.split("-")[0]
    exp = payload.get("exp")

    if not fn or not ln or dob is None or exp is None:
        raise ValueError("missing fields")

    return {
        "first_name": fn,
        "last_name": ln,
        "birth_year": int(birthyear),
        "exp_timestamp": int(exp),
    }

class ScanPopup:
    def __init__(self, root: tk.Tk, on_scan):
        self.root = root
        self.on_scan = on_scan
        self.win = None
        self.entry = None
        self._state_lock = threading.Lock()
        self._placeholder_active = False
        self._open_requested = threading.Event()
        self._hide_requested = threading.Event()
        self._scan_popup_visible = False
        self._selected_camera_index: Optional[int] = None
        self._camera_only_mode = False
        self._camera_cap = None
        self._camera_detector = cv2.QRCodeDetector() if cv2 is not None else None
        self._last_camera_emit_ts = 0.0
        self._last_hotkey_ts = 0.0
        self._camera_window_name = "QR Kamera Live"
        self._camera_window_visible = False
        self._open_in_progress = False

        self._hotkey_handle = keyboard.add_hotkey("F12", self._on_hotkey_press)
        self._esc_handle = keyboard.add_hotkey("esc", self._on_escape_press)

    def _on_hotkey_press(self):
        now = time.monotonic()
        if now - self._last_hotkey_ts < HOTKEY_DEBOUNCE_S:
            return
        self._last_hotkey_ts = now

        if self._camera_only_mode:
            self._camera_window_visible = True
            return

        with self._state_lock:
            if self._scan_popup_visible or self._open_requested.is_set() or self._open_in_progress:
                return
            self._open_requested.set()

    def _on_escape_press(self):
        if self._camera_only_mode and self._camera_window_visible:
            self._close_camera_window()
            return
        self._hide_requested.set()

    def _close_camera_window(self):
        self._camera_window_visible = False
        if cv2 is None:
            return
        try:
            cv2.destroyWindow(self._camera_window_name)
            cv2.waitKey(1)
        except Exception:
            pass

    def process_requests(self):
        should_open = False
        with self._state_lock:
            if self._open_requested.is_set() and not self._open_in_progress:
                self._open_requested.clear()
                self._open_in_progress = True
                should_open = True
        if should_open:
            self.open()
        if self._hide_requested.is_set():
            self._hide_requested.clear()
            self.hide()
        if self._camera_only_mode:
            self._poll_live_camera()

    # trim because qr scanner works somehow only then
    @staticmethod
    def _trim_camera_qr_text(text: str) -> str:
        if len(text) > 172:
            return text[73:-99]
        return text

    def _show_camera_open_failed_dialog(self):
        popup = tk.Toplevel()
        popup.title("Kamera")
        popup.attributes("-topmost", True)
        popup.resizable(False, False)
        tk.Label(popup, text="Kamera kann nicht geöffnet werden").pack(padx=20, pady=14)
        tk.Button(popup, text="OK", width=10, command=popup.destroy).pack(pady=(0, 12))
        popup.update_idletasks()
        x = (popup.winfo_screenwidth() - popup.winfo_width()) // 2
        y = (popup.winfo_screenheight() - popup.winfo_height()) // 2
        popup.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        popup.focus_force()
        popup.wait_window()

    def _enable_camera_only_mode(self, camera_index: int) -> bool:
        if cv2 is None:
            self._show_camera_open_failed_dialog()
            return False

        if self._camera_cap is not None:
            try:
                self._camera_cap.release()
            except Exception:
                pass
            self._camera_cap = None

        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            logger.warning("Failed to open camera index %s", camera_index)
            cap.release()
            self._show_camera_open_failed_dialog()
            return False

        self._camera_cap = cap
        self._selected_camera_index = camera_index
        self._camera_only_mode = True
        self._camera_window_visible = True
        self._open_requested.clear()
        self.hide()
        try:
            cv2.namedWindow(self._camera_window_name, cv2.WINDOW_NORMAL)
            cv2.waitKey(1)
        except Exception:
            pass
        return True

    def _ensure_live_camera(self) -> bool:
        if cv2 is None or self._selected_camera_index is None:
            return False
        if self._camera_cap is not None and self._camera_cap.isOpened():
            return True
        self._camera_cap = cv2.VideoCapture(self._selected_camera_index)
        if not self._camera_cap.isOpened():
            logger.warning("Failed to open camera index %s", self._selected_camera_index)
            self._camera_cap.release()
            self._camera_cap = None
            return False
        return True

    def _poll_live_camera(self):
        if not self._ensure_live_camera() or self._camera_detector is None:
            return

        ok, frame = self._camera_cap.read()
        if not ok or frame is None:
            return

        if not self._camera_window_visible:
            return

        text, points, _ = self._camera_detector.detectAndDecode(frame)
        cv2.imshow(self._camera_window_name, frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            self._close_camera_window()
            return

        try:
            visible = cv2.getWindowProperty(self._camera_window_name, cv2.WND_PROP_VISIBLE)
        except Exception:
            visible = 0
        if visible <= 0:
            self._close_camera_window()
            return

        if points is None or not text:
            return

        text = self._trim_camera_qr_text(text).strip()
        if not text:
            return

        try:
            parse_dokume_qr(text)
        except Exception:
            return

        now = time.time()
        if now - self._last_camera_emit_ts < COOLDOWN_S:
            return
        self._last_camera_emit_ts = now
        self._close_camera_window()
        self.on_scan(text)

    def _add_placeholder(self):
        if not self.entry:
            return
        self.entry.delete(0, tk.END)
        self.entry.insert(0, SCAN_HINT)
        self.entry.config(fg="gray")
        self._placeholder_active = True

    def _clear_placeholder(self):
        if not self.entry or not self._placeholder_active:
            return
        self.entry.delete(0, tk.END)
        self.entry.config(fg="black")
        self._placeholder_active = False

    def open(self):
        with self._state_lock:
            if self.win and self.win.winfo_exists():
                self._scan_popup_visible = True
                needs_focus = True
            else:
                if not self._open_in_progress:
                    self._open_in_progress = True
                self._scan_popup_visible = True
                needs_focus = False
        if needs_focus:
            self._focus()
            return

        try:
            self.win = tk.Toplevel(self.root)
            self.win.title("Scan")
            self.win.attributes("-topmost", True)
            self.win.geometry("800x110+300+200")
            self.win.resizable(False, False)
            self.win.protocol("WM_DELETE_WINDOW", self.hide)

            frame = tk.Frame(self.win, padx=12, pady=12)
            frame.pack(fill="both", expand=True)

            self.entry = tk.Entry(frame, font=("Rubik", 14))
            self.entry.pack(fill="x", expand=True)

            self.win.bind("<Escape>", lambda _event: self.hide())
            self.entry.bind("<Escape>", lambda _event: self.hide())
            self.entry.bind("<Return>", self._submit)
            self.entry.bind("<KeyPress>", lambda _event: self._clear_placeholder())

            self._add_placeholder()
            self.win.wait_visibility()
            self._focus()
        finally:
            with self._state_lock:
                self._open_in_progress = False

    def _focus(self):
        if not (self.win and self.entry):
            return
        self._scan_popup_visible = True
        self.win.deiconify()
        self.win.lift()

        self.win.after(0, lambda: self.win.focus_force())
        self.win.after(10, lambda: self.entry.focus_set())
        self._add_placeholder()

    def hide(self):
        with self._state_lock:
            self._scan_popup_visible = False
        if self.win and self.win.winfo_exists():
            self.win.withdraw()

    def _submit(self, _event=None):
        if not self.entry:
            return
        scanned = self.entry.get().strip()
        logger.info("Scan submitted: len=%s", len(scanned))
        self.entry.delete(0, tk.END)
        self.hide()
        if scanned and scanned != SCAN_HINT:
            self.on_scan(scanned)

    def _show_qr_error_dialog(self) -> str:
        popup_w = 420
        popup_h = 170
        result = {"action": "rescan"}

        popup = tk.Toplevel()
        popup.title("Fehler")
        popup.geometry(f"{popup_w}x{popup_h}")
        popup.resizable(False, False)
        popup.attributes("-topmost", True)

        popup.update_idletasks()
        x = (popup.winfo_screenwidth() - popup_w) // 2
        y = (popup.winfo_screenheight() - popup_h) // 2
        popup.geometry(f"{popup_w}x{popup_h}+{max(x, 0)}+{max(y, 0)}")
        popup.deiconify()
        popup.lift()

        frame = tk.Frame(popup, padx=16, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text=QR_ERROR_TEXT,
            fg="red",
            font=("Rubik", 11, "bold"),
        ).pack(pady=(6, 18))

        btn_row = tk.Frame(frame)
        btn_row.pack()

        def set_action(action: str):
            result["action"] = action
            popup.destroy()

        tk.Button(
            btn_row,
            text="Erneut scannen",
            width=18,
            command=lambda: set_action("rescan"),
        ).pack(side=tk.LEFT, padx=6)

        tk.Button(
            btn_row,
            text="Kamera nehmen",
            width=18,
            command=lambda: set_action("camera"),
        ).pack(side=tk.LEFT, padx=6)

        popup.focus_force()
        popup.update()
        popup.wait_window()
        return result["action"]

    def _select_camera_dialog(self) -> Optional[int]:
        cameras = [] if cv2 is None else list_available_cameras()
        if not cameras:
            logger.warning("No camera devices found.")
            notice = tk.Toplevel()
            notice.title("Kamera")
            notice.attributes("-topmost", True)
            tk.Label(notice, text="Keine Kamera gefunden.").pack(padx=20, pady=14)
            tk.Button(notice, text="OK", width=10, command=notice.destroy).pack(pady=(0, 12))
            notice.update_idletasks()
            x = (notice.winfo_screenwidth() - notice.winfo_width()) // 2
            y = (notice.winfo_screenheight() - notice.winfo_height()) // 2
            notice.geometry(f"+{max(x, 0)}+{max(y, 0)}")
            notice.focus_force()
            notice.wait_window()
            return None

        popup_w = 360
        popup_h = 300
        result = {"index": None}

        popup = tk.Toplevel()
        popup.title("Kamera für QR scanner auswählen")
        popup.geometry(f"{popup_w}x{popup_h}")
        popup.resizable(False, False)
        popup.attributes("-topmost", True)

        popup.update_idletasks()
        x = (popup.winfo_screenwidth() - popup_w) // 2
        y = (popup.winfo_screenheight() - popup_h) // 2
        popup.geometry(f"{popup_w}x{popup_h}+{max(x, 0)}+{max(y, 0)}")
        popup.deiconify()
        popup.lift()

        frame = tk.Frame(popup, padx=12, pady=12)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Verfügbare Kameras:").pack(anchor="w", pady=(0, 8))

        listbox = tk.Listbox(frame, height=10)
        for cam_idx, cam_name in cameras:
            listbox.insert(tk.END, f"[{cam_idx}] {cam_name}")
        listbox.pack(fill="both", expand=True)
        listbox.selection_set(0)

        btn_row = tk.Frame(frame)
        btn_row.pack(pady=(10, 0))

        def choose():
            sel = listbox.curselection()
            if not sel:
                return
            result["index"] = cameras[sel[0]][0]
            popup.destroy()

        tk.Button(btn_row, text="Öffnen", width=14, command=choose).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Abbrechen", width=14, command=popup.destroy).pack(side=tk.LEFT, padx=6)

        popup.focus_force()
        popup.update()
        popup.wait_window()
        return result["index"]

    def _scan_qr_from_camera(self, camera_index: int) -> Optional[str]:
        if cv2 is None:
            logger.warning("OpenCV is not installed, camera QR scan unavailable.")
            return None

        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            logger.warning("Failed to open camera index %s", camera_index)
            cap.release()
            return None

        detector = cv2.QRCodeDetector()
        window_name = f"QR Kamera [{camera_index}]"

        try:
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    return None

                text, points, _ = detector.detectAndDecode(frame)
                if points is not None and text:
                    text = self._trim_camera_qr_text(text)
                    cv2.imshow(window_name, frame)
                    cv2.waitKey(150)
                    return text.strip()

                cv2.imshow(window_name, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    return None
        finally:
            cap.release()
            try:
                cv2.destroyWindow(window_name)
            except Exception:
                cv2.destroyAllWindows()

    def resolve_scanned_qr(self, scanned: str) -> Optional[dict]:
        logger.info("Resolving scanned QR")
        try:
            return parse_dokume_qr(scanned)
        except Exception as e:
            logger.warning("Parse failed: %s", e)
            logger.info("%r", scanned)

        while True:
            action = self._show_qr_error_dialog()
            if action == "rescan":
                self.open()
                return None

            while True:
                camera_index = self._selected_camera_index
                if camera_index is None:
                    camera_index = self._select_camera_dialog()
                if camera_index is None:
                    self.open()
                    return None

                if self._enable_camera_only_mode(camera_index):
                    return None

                # Camera unavailable: force re-selection from list.
                self._selected_camera_index = None

    def close(self):
        if self._hotkey_handle is not None:
            keyboard.remove_hotkey(self._hotkey_handle)
        keyboard.remove_hotkey(self._esc_handle)
        if self._camera_cap is not None:
            self._camera_cap.release()
            self._camera_cap = None
            self._close_camera_window()
        if self.win and self.win.winfo_exists():
            self._scan_popup_visible = False
            self.win.destroy()


async def main():
    ws = WebSocketClient(URL)
    qr_client = QRClient(ws)
    root = tk.Tk()
    root.withdraw()
    send_queue: asyncio.Queue[dict] = asyncio.Queue()

    async def connect_with_retry():
        while True:
            try:
                await ws.connect()
                logger.info("WS connected: %s", URL)
                return
            except (OSError, websockets.WebSocketException) as exc:
                logger.warning("WS connect failed, retry in %.1fs: %s", RECONNECT_DELAY_S, exc)
                await asyncio.sleep(RECONNECT_DELAY_S)

    def on_scan(scanned: str):
        try:
            info = popup.resolve_scanned_qr(scanned)
            if info is not None:
                send_queue.put_nowait(info)
        except Exception:
            logger.exception("on_scan failed")

    popup = ScanPopup(root, on_scan)

    try:
        await connect_with_retry()
        await qr_client.register()
        while True:
            popup.process_requests()
            root.update_idletasks()
            root.update()

            try:
                while True:
                    info = send_queue.get_nowait()
                    while True:
                        try:
                            await qr_client.send_qr(info)
                            logger.info("Sent QR")
                            break
                        except WebSocketDisconnected as exc:
                            logger.warning("WS send failed, reconnecting: %s", exc)
                            await connect_with_retry()
                            await qr_client.register()
            except asyncio.QueueEmpty:
                pass

            try:
                msg = await asyncio.wait_for(ws.recv_json(), timeout=0.01)
            except asyncio.TimeoutError:
                msg = None
            except WebSocketDisconnected as exc:
                logger.warning("WS recv failed, reconnecting: %s", exc)
                await connect_with_retry()
                await qr_client.register()
                msg = None

            if msg and msg.get("type") == "OPEN_CAMERA_SELECTION":
                camera_index = popup._select_camera_dialog()
                if camera_index is not None:
                    popup._selected_camera_index = camera_index
                    popup._enable_camera_only_mode(camera_index)

            await asyncio.sleep(0.03)
    except tk.TclError:
        return
    finally:
        popup.close()
        try:
            root.destroy()
        except tk.TclError:
            pass
        await ws.close()


if __name__ == "__main__":
    asyncio.run(main())
