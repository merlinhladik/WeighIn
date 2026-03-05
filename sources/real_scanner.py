# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

import threading
import base64
import json
import asyncio
import time
import queue
import tkinter as tk
from wsclient import WebSocketClient, QRClient
import keyboard
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

URL = "ws://localhost:8765"
COOLDOWN_S = 1.0
SCAN_HINT = "Bitte den QR scannen und hier nichts eintippen"


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
        self._placeholder_active = False
        self._open_requested = threading.Event()
        self._hide_requested = threading.Event()

        self._hotkey_handle = keyboard.add_hotkey("F12", self._on_hotkey_press)
        self._esc_handle = keyboard.add_hotkey("esc", self._on_escape_press)

    def _on_hotkey_press(self):
        self._open_requested.set()

    def _on_escape_press(self):
        self._hide_requested.set()

    def process_requests(self):
        if self._open_requested.is_set():
            self._open_requested.clear()
            self.open()
        if self._hide_requested.is_set():
            self._hide_requested.clear()
            self.hide()

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
        if self.win and self.win.winfo_exists():
            self._focus()
            return

        self.win = tk.Toplevel(self.root)
        self.win.title("Scan")
        self.win.attributes("-topmost", True)
        self.win.geometry("800x110+300+200")
        self.win.resizable(False, False)

        frame = tk.Frame(self.win, padx=12, pady=12)
        frame.pack(fill="both", expand=True)

        self.entry = tk.Entry(frame, font=("Consolas", 14))
        self.entry.pack(fill="x", expand=True)

        self.win.bind("<Escape>", lambda _event: self.hide())
        self.entry.bind("<Return>", self._submit)
        self.entry.bind("<KeyPress>", lambda _event: self._clear_placeholder())

        self._add_placeholder()
        self.win.wait_visibility()
        self._focus()

    def _focus(self):
        if not (self.win and self.entry):
            return
        self.win.deiconify()
        self.win.lift()

        self.win.after(0, lambda: self.win.focus_force())
        self.win.after(10, lambda: self.entry.focus_set())
        self._add_placeholder()

    def hide(self):
        if self.win and self.win.winfo_exists():
            self.win.withdraw()

    def _submit(self, _event=None):
        if not self.entry:
            return
        scanned = self.entry.get().strip()
        self.entry.delete(0, tk.END)
        self.hide()
        if scanned and scanned != SCAN_HINT:
            self.on_scan(scanned)

    def close(self):
        keyboard.remove_hotkey(self._hotkey_handle)
        keyboard.remove_hotkey(self._esc_handle)
        if self.win and self.win.winfo_exists():
            self.win.destroy()


def read_scanner_lines_blocking():
    root = tk.Tk()
    root.withdraw()
    scanned_lines: queue.Queue[str] = queue.Queue()
    popup = ScanPopup(root, scanned_lines.put)

    try:
        while True:
            popup.process_requests()
            root.update_idletasks()
            root.update()
            try:
                line = scanned_lines.get_nowait()
            except queue.Empty:
                time.sleep(0.01)
                continue
            if line:
                yield line
    except tk.TclError:
        return
    finally:
        popup.close()
        try:
            root.destroy()
        except tk.TclError:
            pass

async def main():
    ws = WebSocketClient(URL)
    await ws.connect()
    qr_client = QRClient(ws)
    logger.info("WS connected: %s", URL)

    q: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def scanner_thread():
        try:
            for line in read_scanner_lines_blocking():
                loop.call_soon_threadsafe(q.put_nowait, line)
        except Exception as e:
            loop.call_soon_threadsafe(q.put_nowait, f"__ERROR__:{e}")

    t = threading.Thread(target=scanner_thread, daemon=True)
    t.start()

    try:
        while True:
            scanned = await q.get()
            if scanned.startswith("__ERROR__:"):
                logger.error(scanned)
                continue

            try:
                info = parse_dokume_qr(scanned)
            except Exception as e:
                logger.warning("Parse failed: %s", e)
                logger.info("%r", scanned)
                continue

            await qr_client.send_qr(info)
            logger.info("Sent QR")
    finally:
        await ws.close()

if __name__ == "__main__":
    asyncio.run(main())
