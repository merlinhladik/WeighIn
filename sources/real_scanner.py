# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

import threading
import base64
import json
import asyncio
import time
import os
import sys
import tkinter as tk
from typing import Optional, Tuple
from shared.wsclient import WebSocketClient, QRClient, WebSocketDisconnected
from shared.logging_config import configure_logging
import keyboard
import websockets
from shared.list_available_cameras import list_available_cameras
from shared.camera_backend import open_capture
from shared.settings import ws_client_url

try:
    import cv2
except Exception:
    cv2 = None

logger = configure_logging("real_scanner")

# Connect target of the GUI WebSocket server; configurable via
# ~/.weighin/settings.json (ws_host / ws_port).
URL = ws_client_url()
COOLDOWN_S = 1.0
HOTKEY_DEBOUNCE_S = 0.35
SCAN_HINT = "Bitte den QR scannen und hier nichts eintippen"
QR_ERROR_TEXT = "Error: Qr kann nicht erkannt werden"
RECONNECT_DELAY_S = 2.0
MODE_IDLE = "idle"
MODE_POPUP = "popup"
MODE_CAMERA_SELECTION = "camera_selection"
MODE_CAMERA = "camera"

# Streaming-Modus (Mac/Headless): wenn WEIGHIN_SCANNER_CAMERA gesetzt ist,
# wird die Kamera dauerhaft geoeffnet, der Feed an die GUI gestreamt und
# QR-Codes laufend erkannt - ohne Tk-Popups.
SCANNER_STREAM_FPS = 12.0
SCANNER_STREAM_INTERVAL_S = 1.0 / SCANNER_STREAM_FPS
SCANNER_FRAME_TARGET_WIDTH = 480
SCANNER_FRAME_JPEG_QUALITY = 70

# Capture resolution we request from the camera. Wide-angle externals (e.g.
# Logitech Brio) render the held pass small; full HD gives the QR enough pixels.
SCANNER_CAPTURE_WIDTH = 1920
SCANNER_CAPTURE_HEIGHT = 1080
# Center-ROI fallback for QR detection: when the full frame yields nothing, the
# pass is usually small and centred (wide FOV) — re-detect on an upscaled centre
# crop so a fixed-focus camera can decode it from a comfortable (in-focus)
# distance. ROI = central fraction of the frame, then upscaled.
SCANNER_ROI_FRACTION = 0.55
SCANNER_ROI_UPSCALE = 2.0


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
        self._mode = MODE_IDLE
        self._scan_popup_request = False
        self._selected_camera_index: Optional[int] = None
        self._camera_selection_running = False
        self._camera_cap = None
        self._camera_detector = cv2.QRCodeDetector() if cv2 is not None else None
        self._last_camera_emit_ts = 0.0
        self._last_hotkey_ts = 0.0
        self._camera_window_name = "QR Kamera Live"

        # Global keyboard hotkeys need root on macOS/Linux; without it the
        # `keyboard` listener thread raises "Error 13 - Must be run as
        # administrator" and dumps a traceback. Register only when privileged —
        # the GUI keeps its own in-app Tkinter F12 either way.
        self._hotkey_handle = None
        self._esc_handle = None
        if self._can_use_global_hotkeys():
            try:
                self._hotkey_handle = keyboard.add_hotkey("F12", self._on_hotkey_press)
                self._esc_handle = keyboard.add_hotkey("esc", self._on_escape_press)
            except Exception:
                logger.warning("Globale Hotkeys konnten nicht registriert werden", exc_info=True)
        else:
            logger.warning(
                "Globale Tastatur-Hotkeys (F12/Esc) deaktiviert — benötigen Root "
                "auf macOS/Linux. Ohne sudo läuft der Scanner ohne globalen Hotkey "
                "(die GUI-interne F12-Taste funktioniert weiterhin)."
            )

    def _get_mode(self) -> str:
        with self._state_lock:
            return self._mode

    def _set_mode(self, mode: str):
        with self._state_lock:
            self._mode = mode

    def _transition_mode(self, allowed_from: Tuple[str, ...], target: str) -> bool:
        with self._state_lock:
            if self._mode not in allowed_from:
                return False
            self._mode = target
            return True

    def _request_scan_popup(self):
        with self._state_lock:
            if self._scan_popup_request or self._mode != MODE_IDLE:
                return
            self._scan_popup_request = True

    def _consume_scan_popup_request(self) -> bool:
        with self._state_lock:
            if not self._scan_popup_request:
                return False
            self._scan_popup_request = False
            if self._mode != MODE_IDLE:
                return False
            self._mode = MODE_POPUP
            return True

    def _on_hotkey_press(self):
        now = time.monotonic()
        if now - self._last_hotkey_ts < HOTKEY_DEBOUNCE_S:
            return
        self._last_hotkey_ts = now

        self._request_scan_popup()

    def _on_escape_press(self):
        mode = self._get_mode()
        if mode in (MODE_POPUP, MODE_CAMERA):
            self._set_mode(MODE_IDLE)

    def _popup_is_visible(self) -> bool:
        if not (self.win and self.win.winfo_exists()):
            return False
        return self.win.state() != "withdrawn"

    def _close_camera_window(self):
        if cv2 is None:
            return
        try:
            cv2.destroyWindow(self._camera_window_name)
            cv2.waitKey(1)
        except Exception:
            try:
                cv2.destroyAllWindows()
                cv2.waitKey(1)
            except Exception:
                pass

    def process_requests(self):
        self._consume_scan_popup_request()
        mode = self._get_mode()

        if mode == MODE_POPUP:
            if not (self.win and self.win.winfo_exists()):
                self.open()
        else:
            self.hide(change_mode=False)

        if mode == MODE_CAMERA_SELECTION:
            self._run_camera_selection(return_to_popup=False)
            return

        if mode == MODE_CAMERA:
            self._poll_live_camera()
            return

        self._stop_camera_scan()

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

    def _show_camera_in_use_dialog(self):
        popup = tk.Toplevel()
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

    def _show_camera_probe_dialog(self):
        popup = tk.Toplevel()
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
        popup.geometry(f"300x100+{max(x, 0)}+{max(y, 0)}")
        popup.focus_force()
        popup.grab_set()
        popup.update()
        return popup

    def _close_camera_probe_dialog(self, popup):
        if popup is None:
            return
        try:
            popup.grab_release()
        except Exception:
            pass
        try:
            popup.destroy()
        except tk.TclError:
            pass

    def _camera_name_for_index(self, camera_index: int) -> str:
        cameras = [] if cv2 is None else list_available_cameras()
        for idx, name in cameras:
            if idx == camera_index:
                return name
        return f"Kamera {camera_index}"

    def _show_camera_probe_success_dialog(self, camera_name: str):
        popup = tk.Toplevel()
        popup.title("Kamera")
        popup.attributes("-topmost", True)
        popup.resizable(False, False)
        tk.Label(
            popup,
            text=f"{camera_name}\nerfolgreich eingesetzt für Scanner",
            justify="center",
            wraplength=340,
        ).pack(padx=20, pady=14)
        tk.Button(popup, text="OK", width=10, command=popup.destroy).pack(pady=(0, 12))
        popup.update_idletasks()
        x = (popup.winfo_screenwidth() - popup.winfo_width()) // 2
        y = (popup.winfo_screenheight() - popup.winfo_height()) // 2
        popup.geometry(f"400x100+{max(x, 0)}+{max(y, 0)}")
        popup.focus_force()
        popup.wait_window()

    def _reset_selected_camera(self):
        self._selected_camera_index = None

    def _try_mark_camera_selection_running(self) -> bool:
        with self._state_lock:
            if self._camera_selection_running:
                return False
            self._camera_selection_running = True
            return True

    def _clear_camera_selection_running(self):
        with self._state_lock:
            self._camera_selection_running = False

    def request_camera_selection(self):
        with self._state_lock:
            if self._camera_selection_running:
                return
        if not self._transition_mode((MODE_IDLE,), MODE_CAMERA_SELECTION):
            return

    def request_scan_popup(self):
        self._request_scan_popup()

    def _camera_frame_looks_blocked(self, frame) -> bool:
        if cv2 is None or frame is None:
            return True
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mean, stddev = cv2.meanStdDev(gray)
        except Exception:
            return True

        brightness = float(mean[0][0])
        contrast = float(stddev[0][0])
        return brightness <= 3.0 or contrast <= 1.0

    def _probe_selected_camera(self, camera_index: int) -> bool:
        if cv2 is None:
            return False

        checking_popup = self._show_camera_probe_dialog()
        cap = open_capture(camera_index)
        if not cap.isOpened():
            logger.warning("Camera index %s is not opened during probe", camera_index)
            cap.release()
            self._close_camera_probe_dialog(checking_popup)
            return False

        try:
            # macOS-AVFoundation: laengere Aufwaermphase + Logging.
            time.sleep(1.5)
            good_frames = 0
            for attempt in range(20):
                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(0.1)
                    continue
                blocked = self._camera_frame_looks_blocked(frame)
                try:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    mean, stddev = cv2.meanStdDev(gray)
                    logger.info(
                        "scan-probe cam=%s attempt=%s brightness=%.2f contrast=%.2f blocked=%s",
                        camera_index, attempt, float(mean[0][0]), float(stddev[0][0]), blocked,
                    )
                except Exception:
                    pass
                if blocked:
                    time.sleep(0.1)
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
            self._close_camera_probe_dialog(checking_popup)

    def _start_live_camera_scan(self, camera_index: int, return_to_popup: bool = False) -> bool:
        if cv2 is None:
            self._show_camera_open_failed_dialog()
            self._set_mode(MODE_POPUP if return_to_popup else MODE_IDLE)
            return False

        if (
            self._camera_cap is not None
            and (
                self._selected_camera_index != camera_index
                or not self._camera_cap.isOpened()
            )
        ):
            try:
                self._camera_cap.release()
            except Exception:
                pass
            self._camera_cap = None

        if self._camera_cap is None:
            cap = open_capture(camera_index)
            if not cap.isOpened():
                logger.warning("Failed to open camera index %s", camera_index)
                cap.release()
                self._show_camera_open_failed_dialog()
                self._set_mode(MODE_POPUP if return_to_popup else MODE_IDLE)
                return False
            self._camera_cap = cap

        self._selected_camera_index = camera_index
        self._set_mode(MODE_CAMERA)
        self.hide(change_mode=False)
        try:
            cv2.namedWindow(self._camera_window_name, cv2.WINDOW_NORMAL)
            cv2.waitKey(1)
        except Exception:
            pass
        return True

    def _stop_camera_scan(self):
        if self._camera_cap is not None:
            try:
                self._camera_cap.release()
            except Exception:
                pass
            self._camera_cap = None
        self._close_camera_window()

    def _ensure_live_camera(self) -> bool:
        if self._get_mode() != MODE_CAMERA:
            self._stop_camera_scan()
            return False
        if cv2 is None or self._selected_camera_index is None:
            return False
        return self._camera_cap is not None and self._camera_cap.isOpened()

    def _poll_live_camera(self):
        if not self._ensure_live_camera() or self._camera_detector is None:
            self._set_mode(MODE_IDLE)
            self._stop_camera_scan()
            return

        ok, frame = self._camera_cap.read()
        if not ok or frame is None:
            self._set_mode(MODE_IDLE)
            self._stop_camera_scan()
            self._reset_selected_camera()
            self._show_camera_in_use_dialog()
            return

        text, points, _ = self._camera_detector.detectAndDecode(frame)
        cv2.imshow(self._camera_window_name, frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            self._set_mode(MODE_IDLE)
            self._stop_camera_scan()
            return

        try:
            visible = cv2.getWindowProperty(self._camera_window_name, cv2.WND_PROP_VISIBLE)
        except Exception:
            visible = 0
        if visible <= 0:
            self._set_mode(MODE_IDLE)
            self._stop_camera_scan()
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
        self._set_mode(MODE_IDLE)
        self._stop_camera_scan()
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
        if self._popup_is_visible():
            return

        if self.win and self.win.winfo_exists():
            self._focus()
            return

        try:
            self.win = tk.Toplevel(self.root)
            self.win.title("Scan")
            self.win.attributes("-topmost", True)
            self.win.geometry("800x150+300+200")
            self.win.resizable(False, False)
            self.win.protocol("WM_DELETE_WINDOW", lambda: self.hide())

            frame = tk.Frame(self.win, padx=12, pady=12)
            frame.pack(fill="both", expand=True)

            self.entry = tk.Entry(frame, font=("Rubik", 14))
            self.entry.pack(fill="x", expand=True)

            tk.Button(
                frame,
                text="Mit Kamera scannen",
                width=20,
                command=self._open_camera_scan_from_popup,
            ).pack(anchor="e", pady=(12, 0))

            self.win.bind("<Escape>", lambda _event: self.hide())
            self.entry.bind("<Escape>", lambda _event: self.hide())
            self.entry.bind("<Return>", self._submit)
            self.entry.bind("<KeyPress>", lambda _event: self._clear_placeholder())

            self._add_placeholder()
            self.win.wait_visibility()
            self._focus()
        except tk.TclError:
            self._set_mode(MODE_IDLE)

    def _focus(self):
        if not (self.win and self.entry):
            return
        self.win.deiconify()
        self.win.lift()

        self.win.after(0, lambda: self.win.focus_force())
        self.win.after(10, lambda: self.entry.focus_set())
        self._add_placeholder()

    def hide(self, change_mode: bool = True):
        if change_mode:
            self._set_mode(MODE_IDLE)
        if self.win and self.win.winfo_exists():
            try:
                self.win.destroy()
            except tk.TclError:
                pass
        self.win = None
        self.entry = None
        self._placeholder_active = False

    def _open_camera_scan_from_popup(self):
        camera_index = self._selected_camera_index
        if camera_index is None:
            self._set_mode(MODE_CAMERA_SELECTION)
            self.hide(change_mode=False)
            self._run_camera_selection(return_to_popup=True)
            return
        self._start_live_camera_scan(camera_index, return_to_popup=True)

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

    def _run_camera_selection(self, return_to_popup: bool):
        if self._get_mode() != MODE_CAMERA_SELECTION:
            return
        if not self._try_mark_camera_selection_running():
            return

        try:
            while self._get_mode() == MODE_CAMERA_SELECTION:
                camera_index = self._select_camera_dialog()
                if camera_index is None:
                    self._set_mode(MODE_POPUP if return_to_popup else MODE_IDLE)
                    if return_to_popup:
                        self.open()
                    return

                if self._probe_selected_camera(camera_index):
                    self._selected_camera_index = camera_index
                    self._show_camera_probe_success_dialog(self._camera_name_for_index(camera_index))
                    self._start_live_camera_scan(camera_index, return_to_popup=return_to_popup)
                    return

                self._show_camera_in_use_dialog()
        finally:
            self._clear_camera_selection_running()

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
                self._set_mode(MODE_POPUP)
                self.open()
                return None

            camera_index = self._selected_camera_index
            if camera_index is None:
                self._set_mode(MODE_CAMERA_SELECTION)
                self._run_camera_selection(return_to_popup=True)
                return None

            self._start_live_camera_scan(camera_index, return_to_popup=True)
            return None

    @staticmethod
    def _can_use_global_hotkeys() -> bool:
        """The `keyboard` lib needs root on macOS/Linux (else Error 13 in its
        listener thread). Windows works without elevation."""
        if os.name == "nt":
            return True
        try:
            return os.geteuid() == 0
        except AttributeError:
            return False

    def close(self):
        if self._hotkey_handle is not None:
            keyboard.remove_hotkey(self._hotkey_handle)
        if self._esc_handle is not None:
            keyboard.remove_hotkey(self._esc_handle)
        self._stop_camera_scan()
        if self.win and self.win.winfo_exists():
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
    shutdown_requested = False

    try:
        await connect_with_retry()
        await qr_client.register()
        while True:
            if shutdown_requested:
                logger.info("Shutdown requested by GUI message")
                break

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

            if msg:
                msg_type = msg.get("type")
                if msg_type == "SHUTDOWN":
                    shutdown_requested = True
                    continue
                if msg_type == "OPEN_CAMERA_SELECTION":
                    popup.request_camera_selection()
                if msg_type == "OPEN_SCAN_POPUP":
                    popup.request_scan_popup()

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


def _request_capture_resolution(cap):
    """Best-effort: ask the camera for full HD. Unsupported values are ignored
    by the backend, so this is safe for any camera."""
    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, SCANNER_CAPTURE_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, SCANNER_CAPTURE_HEIGHT)
    except Exception:
        pass


def _build_detectors():
    """QR detectors to try in order. The ArUco-based detector (OpenCV ≥4.7) is
    often more tolerant of small/angled codes than the classic one; both decode
    standard QR. Classic first (fastest), ArUco as fallback."""
    dets = [cv2.QRCodeDetector()]
    try:
        dets.append(cv2.QRCodeDetectorAruco())
    except Exception:
        pass
    return dets


def _try_decode(detector, img):
    try:
        text, points, _ = detector.detectAndDecode(img)
    except Exception:
        return "", None
    return text, points


def _detect_qr(detectors, frame):
    """Detect+decode a QR. Tries each detector on the full frame and on an
    upscaled centre crop. Wide-angle / fixed-focus cameras (e.g. Brio) render a
    held pass small and central — the centre-ROI retry gives the detector more
    pixels on the code. Returns (text, points)."""
    h, w = frame.shape[:2]
    cw, ch = int(w * SCANNER_ROI_FRACTION), int(h * SCANNER_ROI_FRACTION)
    roi = None
    if cw >= 8 and ch >= 8:
        x0, y0 = (w - cw) // 2, (h - ch) // 2
        roi = frame[y0:y0 + ch, x0:x0 + cw]
        if SCANNER_ROI_UPSCALE != 1.0:
            roi = cv2.resize(
                roi, (int(cw * SCANNER_ROI_UPSCALE), int(ch * SCANNER_ROI_UPSCALE)),
                interpolation=cv2.INTER_CUBIC,
            )
    for det in detectors:
        for img in (frame, roi):
            if img is None:
                continue
            text, points = _try_decode(det, img)
            if points is not None and text:
                return text, points
    return "", None


def _camera_candidates(start_index: int, max_search: int = 6):
    """Reihenfolge, in der Kamera-Indizes durchprobiert werden.

    Erst die konfigurierte Kamera, dann jede andere enumerierte (per pygrabber),
    danach 0..max_search-1 als Auffangnetz. So weicht der Scanner automatisch auf
    eine funktionierende Kamera aus, wenn der gespeicherte Index belegt oder
    abgezogen ist (analog zu weight._open_first_working_camera).
    """
    listed = [idx for idx, _ in list_available_cameras()]
    candidates = []
    if start_index in listed:
        candidates.append(start_index)
    candidates.extend(idx for idx in listed if idx != start_index)
    candidates.extend(idx for idx in range(max_search) if idx not in candidates)
    return candidates


async def _streaming_main(scanner_cam_index: int):
    """
    Dialog-freier Streaming-Modus: oeffnet die Kamera einmal, streamt Frames
    via WS an die GUI (FRAME_SCANNER), erkennt QR-Codes laufend mit Cooldown.
    Aktiv nur wenn WEIGHIN_SCANNER_CAMERA gesetzt ist.
    """
    if cv2 is None:
        logger.error("cv2 nicht verfuegbar - Streaming-Modus unmoeglich")
        return

    # Erst die konfigurierte Kamera, dann Fallback auf jede andere verfuegbare
    # (belegter/abgezogener Index). macOS-TCC-Race: erster Open kann False
    # liefern bis die Permission durch ist -> mehrere Runden ueber alle Kandidaten.
    cap = None
    candidates = _camera_candidates(scanner_cam_index)
    for attempt in range(6):
        for idx in candidates:
            cap = open_capture(idx)
            if cap.isOpened():
                if idx != scanner_cam_index:
                    logger.warning(
                        "Scanner-Kamera index=%s nicht nutzbar - Fallback auf index=%s",
                        scanner_cam_index, idx,
                    )
                scanner_cam_index = idx
                break
            cap.release()
            cap = None
        if cap is not None:
            break
        logger.warning(
            "Keine Scanner-Kamera offen (attempt %s/6, Kandidaten=%s) - TCC retry in 1.5s",
            attempt + 1, candidates,
        )
        await asyncio.sleep(1.5)
    if cap is None:
        logger.error(
            "Keine Scanner-Kamera oeffenbar (Kandidaten=%s)", candidates,
        )
        return
    logger.info("Scanner-Kamera index=%s geoeffnet (Streaming-Modus)", scanner_cam_index)
    _request_capture_resolution(cap)

    detectors = _build_detectors()
    ws = WebSocketClient(URL)
    qr_client = QRClient(ws)
    last_emit_ts = 0.0
    last_frame_send = 0.0

    async def connect_with_retry():
        while True:
            try:
                await ws.connect()
                logger.info("WS connected: %s", URL)
                return
            except (OSError, websockets.WebSocketException) as exc:
                logger.warning(
                    "WS connect failed, retry in %.1fs: %s", RECONNECT_DELAY_S, exc
                )
                await asyncio.sleep(RECONNECT_DELAY_S)

    try:
        await connect_with_retry()
        await qr_client.register()

        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                logger.warning("Scanner-Kamera read fehlgeschlagen")
                await asyncio.sleep(0.05)
                continue

            # Frame-Streaming an GUI
            now_mono = time.monotonic()
            if now_mono - last_frame_send >= SCANNER_STREAM_INTERVAL_S:
                last_frame_send = now_mono
                h, w = frame.shape[:2]
                if w > SCANNER_FRAME_TARGET_WIDTH:
                    s = SCANNER_FRAME_TARGET_WIDTH / w
                    small = cv2.resize(frame, (SCANNER_FRAME_TARGET_WIDTH, int(h * s)))
                else:
                    small = frame
                ok_enc, jpeg = cv2.imencode(
                    ".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, SCANNER_FRAME_JPEG_QUALITY]
                )
                if ok_enc:
                    try:
                        await ws.send_json({
                            "type": "FRAME_SCANNER",
                            "data": base64.b64encode(jpeg.tobytes()).decode("ascii"),
                        })
                    except WebSocketDisconnected:
                        await connect_with_retry()
                        await qr_client.register()

            # QR-Detection: mehrere Detektoren, Vollbild + Center-ROI-Fallback
            text, points = _detect_qr(detectors, frame)

            if points is not None and text:
                trimmed = ScanPopup._trim_camera_qr_text(text).strip()
                if trimmed and time.time() - last_emit_ts > COOLDOWN_S:
                    try:
                        info = parse_dokume_qr(trimmed)
                    except Exception:
                        info = None
                    if info is not None:
                        last_emit_ts = time.time()
                        try:
                            await qr_client.send_qr(info)
                            logger.info("Sent QR")
                        except WebSocketDisconnected:
                            await connect_with_retry()
                            await qr_client.register()

            # Eingehende Steuermsgs verarbeiten
            try:
                msg = await asyncio.wait_for(ws.recv_json(), timeout=0.01)
            except asyncio.TimeoutError:
                msg = None
            except WebSocketDisconnected:
                await connect_with_retry()
                await qr_client.register()
                msg = None
            if msg:
                msg_type = msg.get("type")
                if msg_type == "SHUTDOWN":
                    logger.info("Shutdown by GUI message")
                    break
                if msg_type == "SET_CAMERA":
                    target_idx = msg.get("index")
                    if isinstance(target_idx, int):
                        logger.info("SET_CAMERA -> index=%s", target_idx)
                        cap.release()
                        new_cap = open_capture(target_idx)
                        if new_cap.isOpened():
                            cap = new_cap
                            scanner_cam_index = target_idx
                            _request_capture_resolution(cap)
                        else:
                            new_cap.release()
                            logger.warning(
                                "SET_CAMERA failed for index %s, restoring previous %s",
                                target_idx, scanner_cam_index,
                            )
                            cap = open_capture(scanner_cam_index)

            await asyncio.sleep(0.005)
    finally:
        cap.release()
        await ws.close()


if __name__ == "__main__":
    logger.info(
        "[STARTUP] real_scanner boot pid=%s executable=%s argv=%s cwd=%s",
        os.getpid(),
        sys.executable,
        sys.argv,
        os.getcwd(),
    )
    scanner_env = os.environ.get("WEIGHIN_SCANNER_CAMERA", "").strip()
    if scanner_env:
        try:
            scanner_idx = int(scanner_env)
        except ValueError:
            logger.warning(
                "WEIGHIN_SCANNER_CAMERA=%r ist kein int, fallback auf Popup-Modus",
                scanner_env,
            )
            scanner_idx = None
        if scanner_idx is not None:
            asyncio.run(_streaming_main(scanner_idx))
            sys.exit(0)
    asyncio.run(main())
