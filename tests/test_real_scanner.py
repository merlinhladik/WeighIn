import asyncio
import base64
import json
import threading
import queue

import pytest

import real_scanner


def _payload_token(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{encoded}.ignored.signature"


def test_scanpopup_process_requests_runs_open_and_hide_handlers():
    popup = real_scanner.ScanPopup.__new__(real_scanner.ScanPopup)
    popup._open_requested = threading.Event()
    popup._hide_requested = threading.Event()

    calls = []
    popup.open = lambda: calls.append("open")
    popup.hide = lambda: calls.append("hide")

    popup._open_requested.set()
    popup._hide_requested.set()
    popup.process_requests()

    assert calls == ["open", "hide"]
    assert popup._open_requested.is_set() is False
    assert popup._hide_requested.is_set() is False


def test_scanpopup_init_registers_hotkeys_and_press_handlers_set_events(monkeypatch):
    registered = []

    def fake_add_hotkey(key, callback):
        registered.append((key, callback))
        return f"handle-{key}"

    monkeypatch.setattr(real_scanner.keyboard, "add_hotkey", fake_add_hotkey)

    popup = real_scanner.ScanPopup(object(), lambda value: value)

    assert popup._hotkey_handle == "handle-F12"
    assert popup._esc_handle == "handle-esc"
    assert [item[0] for item in registered] == ["F12", "esc"]

    popup._on_hotkey_press()
    popup._on_escape_press()

    assert popup._open_requested.is_set() is True
    assert popup._hide_requested.is_set() is True


def test_scanpopup_placeholder_helpers_update_entry_state():
    class DummyEntry:
        def __init__(self):
            self.value = ""
            self.deleted = []
            self.config_calls = []

        def delete(self, start, end):
            self.deleted.append((start, end))
            self.value = ""

        def insert(self, _idx, value):
            self.value = value

        def config(self, **kwargs):
            self.config_calls.append(kwargs)

    popup = real_scanner.ScanPopup.__new__(real_scanner.ScanPopup)
    popup.entry = DummyEntry()
    popup._placeholder_active = False

    popup._add_placeholder()
    assert popup.entry.value == real_scanner.SCAN_HINT
    assert popup._placeholder_active is True
    assert popup.entry.config_calls[-1] == {"fg": "gray"}

    popup._clear_placeholder()
    assert popup.entry.value == ""
    assert popup._placeholder_active is False
    assert popup.entry.config_calls[-1] == {"fg": "black"}


def test_scanpopup_open_focus_hide_and_close(monkeypatch):
    windows = []
    removed_hotkeys = []

    class FakeWin:
        def __init__(self, _root):
            self.exists = True
            self.binds = []
            self.after_calls = []
            self.withdrawn = False
            self.destroyed = False
            self.deiconified = False
            self.lifted = False
            self.focused = False
            windows.append(self)

        def winfo_exists(self):
            return self.exists

        def title(self, _value):
            return None

        def attributes(self, *_args):
            return None

        def geometry(self, _value):
            return None

        def resizable(self, *_args):
            return None

        def bind(self, event, callback):
            self.binds.append((event, callback))

        def wait_visibility(self):
            return None

        def deiconify(self):
            self.deiconified = True

        def lift(self):
            self.lifted = True

        def after(self, delay, callback):
            self.after_calls.append(delay)
            callback()

        def focus_force(self):
            self.focused = True

        def withdraw(self):
            self.withdrawn = True

        def destroy(self):
            self.destroyed = True

    class FakeFrame:
        def __init__(self, _parent, **_kwargs):
            return None

        def pack(self, **_kwargs):
            return None

    class FakeEntry:
        def __init__(self, _parent, **_kwargs):
            self.value = ""
            self.binds = []
            self.focused = False
            self.config_calls = []

        def pack(self, **_kwargs):
            return None

        def bind(self, event, callback):
            self.binds.append((event, callback))

        def delete(self, _start, _end):
            self.value = ""

        def insert(self, _idx, value):
            self.value = value

        def config(self, **kwargs):
            self.config_calls.append(kwargs)

        def focus_set(self):
            self.focused = True

    monkeypatch.setattr(real_scanner.tk, "Toplevel", FakeWin)
    monkeypatch.setattr(real_scanner.tk, "Frame", FakeFrame)
    monkeypatch.setattr(real_scanner.tk, "Entry", FakeEntry)
    monkeypatch.setattr(real_scanner.keyboard, "remove_hotkey", removed_hotkeys.append)

    popup = real_scanner.ScanPopup.__new__(real_scanner.ScanPopup)
    popup.root = object()
    popup.on_scan = lambda _value: None
    popup.win = None
    popup.entry = None
    popup._placeholder_active = False
    popup._hotkey_handle = "handle-f12"
    popup._esc_handle = "handle-esc"

    popup.open()

    assert len(windows) == 1
    assert popup.entry.value == real_scanner.SCAN_HINT
    assert popup.win.deiconified is True
    assert popup.win.lifted is True
    assert popup.win.focused is True
    assert popup.entry.focused is True
    assert {event for event, _ in popup.win.binds} == {"<Escape>"}
    assert {event for event, _ in popup.entry.binds} == {"<Return>", "<KeyPress>"}

    popup.open()
    assert len(windows) == 1

    popup.hide()
    assert popup.win.withdrawn is True

    popup.close()
    assert removed_hotkeys == ["handle-f12", "handle-esc"]
    assert popup.win.destroyed is True


def test_scanpopup_submit_hides_popup_and_forwards_valid_scan():
    class DummyEntry:
        def __init__(self, value):
            self.value = value
            self.deleted = []

        def get(self):
            return self.value

        def delete(self, start, end):
            self.deleted.append((start, end))

    popup = real_scanner.ScanPopup.__new__(real_scanner.ScanPopup)
    popup.entry = DummyEntry("  qr-token  ")

    scans = []
    hides = []
    popup.on_scan = scans.append
    popup.hide = lambda: hides.append(True)

    popup._submit()

    assert hides == [True]
    assert scans == ["qr-token"]
    assert popup.entry.deleted == [(0, real_scanner.tk.END)]


def test_scanpopup_submit_ignores_placeholder_text():
    class DummyEntry:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

        def delete(self, _start, _end):
            return None

    popup = real_scanner.ScanPopup.__new__(real_scanner.ScanPopup)
    popup.entry = DummyEntry(real_scanner.SCAN_HINT)

    scans = []
    popup.on_scan = scans.append
    popup.hide = lambda: None

    popup._submit()

    assert scans == []


def test_main_parses_scans_and_sends_qr(monkeypatch):
    class StopMain(Exception):
        pass

    token = _payload_token(
        {"FN": "Ada", "LN": "Lovelace", "DOB": "1815-12-10", "exp": 1700000000}
    )

    class DummyWS:
        instance = None

        def __init__(self, url):
            self.url = url
            self.connected = False
            self.closed = False
            DummyWS.instance = self

        async def connect(self):
            self.connected = True

        async def close(self):
            self.closed = True

    class DummyQRClient:
        sent = []

        def __init__(self, ws):
            self.ws = ws

        async def send_qr(self, info):
            DummyQRClient.sent.append(info)
            raise StopMain()

    def fake_reader():
        yield token

    monkeypatch.setattr(real_scanner, "WebSocketClient", DummyWS)
    monkeypatch.setattr(real_scanner, "QRClient", DummyQRClient)
    monkeypatch.setattr(real_scanner, "read_scanner_lines_blocking", fake_reader)

    with pytest.raises(StopMain):
        asyncio.run(real_scanner.main())

    assert DummyWS.instance.connected is True
    assert DummyWS.instance.closed is True
    assert DummyQRClient.sent == [
        {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "birth_year": 1815,
            "exp_timestamp": 1700000000,
        }
    ]


def test_main_skips_invalid_scan_and_continues(monkeypatch):
    class StopMain(Exception):
        pass

    valid_token = _payload_token(
        {"FN": "Grace", "LN": "Hopper", "DOB": "1906-12-09", "exp": 1800000000}
    )

    class DummyWS:
        async def connect(self):
            return None

        async def close(self):
            return None

    class DummyQRClient:
        sent = []

        def __init__(self, ws):
            self.ws = ws

        async def send_qr(self, info):
            DummyQRClient.sent.append(info)
            raise StopMain()

    def fake_reader():
        yield "not-json"
        yield valid_token

    monkeypatch.setattr(real_scanner, "WebSocketClient", lambda _url: DummyWS())
    monkeypatch.setattr(real_scanner, "QRClient", DummyQRClient)
    monkeypatch.setattr(real_scanner, "read_scanner_lines_blocking", fake_reader)

    with pytest.raises(StopMain):
        asyncio.run(real_scanner.main())

    assert DummyQRClient.sent == [
        {
            "first_name": "Grace",
            "last_name": "Hopper",
            "birth_year": 1906,
            "exp_timestamp": 1800000000,
        }
    ]


def test_read_scanner_lines_blocking_yields_lines_and_cleans_up(monkeypatch):
    state = {"withdrawn": False, "destroyed": False, "closed": False}

    class FakeRoot:
        def withdraw(self):
            state["withdrawn"] = True

        def update_idletasks(self):
            return None

        def update(self):
            return None

        def destroy(self):
            state["destroyed"] = True

    class FakePopup:
        def __init__(self, _root, on_scan):
            self.on_scan = on_scan
            self.sent = False

        def process_requests(self):
            if not self.sent:
                self.on_scan("first-scan")
                self.sent = True

        def close(self):
            state["closed"] = True

    monkeypatch.setattr(real_scanner.tk, "Tk", FakeRoot)
    monkeypatch.setattr(real_scanner, "ScanPopup", FakePopup)

    gen = real_scanner.read_scanner_lines_blocking()
    assert next(gen) == "first-scan"
    gen.close()

    assert state == {"withdrawn": True, "destroyed": True, "closed": True}


def test_read_scanner_lines_blocking_handles_tclerror(monkeypatch):
    state = {"closed": False, "destroyed": False}

    class FakeRoot:
        def withdraw(self):
            return None

        def update_idletasks(self):
            return None

        def update(self):
            raise real_scanner.tk.TclError("stop")

        def destroy(self):
            state["destroyed"] = True

    class FakePopup:
        def __init__(self, _root, _on_scan):
            return None

        def process_requests(self):
            return None

        def close(self):
            state["closed"] = True

    monkeypatch.setattr(real_scanner.tk, "Tk", FakeRoot)
    monkeypatch.setattr(real_scanner, "ScanPopup", FakePopup)

    assert list(real_scanner.read_scanner_lines_blocking()) == []
    assert state == {"closed": True, "destroyed": True}
