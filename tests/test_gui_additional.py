import asyncio
import json

import gui
from gui import PAID, UNPAID, VALID_KEY, WEIGHT_KEY, WeighingApp


class DummyField:
    def __init__(self, value=""):
        self.value = value
        self.deleted = []
        self.inserted = []

    def get(self):
        return self.value

    def delete(self, *args):
        self.deleted.append(args)
        self.value = ""

    def insert(self, _idx, value):
        self.inserted.append(value)
        self.value = str(value)


class DummyVar:
    def __init__(self, value=None):
        self.value = value
        self.traces = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def trace(self, *_args):
        self.traces.append(_args)

    def trace_add(self, *_args):
        self.traces.append(_args)


class ConfigRecorder:
    def __init__(self):
        self.config_calls = []

    def config(self, **kwargs):
        self.config_calls.append(kwargs)


def test_gender_normalization_and_status_colors():
    assert WeighingApp.normalize_ui_gender("m") == "maennlich"
    assert WeighingApp.normalize_ui_gender("female") == "weiblich"
    assert WeighingApp.normalize_json_gender("maennlich") == "m"
    assert WeighingApp.normalize_json_gender("unknown") == "w"

    app = type("Dummy", (), {})()
    app.valid_var = DummyVar("gueltig")
    app.paid_var = DummyVar(PAID)
    app.gender_var = DummyVar("maennlich")
    app.val_valid = ConfigRecorder()
    app.val_paid = ConfigRecorder()
    app.val_gender = ConfigRecorder()

    WeighingApp.update_status_dropdown_colors(app)

    assert app.val_valid.config_calls[-1]["bg"] == gui.THEME["success"]
    assert app.val_paid.config_calls[-1]["bg"] == gui.THEME["success"]
    assert app.val_gender.config_calls[-1]["bg"] == gui.THEME["maennlich"]


def test_clear_participant_details_resets_fields():
    app = type("Dummy", (), {})()
    app.selected_participant = {"ID": 1}
    app.val_prename = DummyField("Ada")
    app.val_surname = DummyField("Lovelace")
    app.val_birthyear = DummyField("1815")
    app.val_club = DummyField("TOP")
    app.weight_var = DummyField("75")
    app.valid_var = DummyVar("gueltig")
    app.paid_var = DummyVar(PAID)
    app.gender_var = DummyVar("maennlich")
    updates = []
    app.update_status_dropdown_colors = lambda: updates.append(True)

    WeighingApp.clear_participant_details(app)

    assert app.selected_participant is None
    assert app.val_prename.value == ""
    assert app.val_surname.value == ""
    assert app.val_birthyear.value == ""
    assert app.val_club.value == ""
    assert app.weight_var.value == ""
    assert app.valid_var.value == "ungueltig"
    assert app.paid_var.value == UNPAID
    assert app.gender_var.value == "weiblich"
    assert updates == [True]


def test_filter_list_clears_details_only_for_non_blank_query():
    app = type("Dummy", (), {})()
    app.search_var = DummyVar("ada")
    calls = {"clear": 0, "update": []}
    app.clear_participant_details = lambda: calls.__setitem__("clear", calls["clear"] + 1)
    app.get_filtered_participants = lambda query: [query]
    app.update_list = lambda data: calls["update"].append(data)

    WeighingApp.filter_list(app)

    assert calls == {"clear": 1, "update": [["ada"]]}

    app.search_var = DummyVar("   ")
    calls = {"clear": 0, "update": []}
    app.clear_participant_details = lambda: calls.__setitem__("clear", calls["clear"] + 1)
    app.update_list = lambda data: calls["update"].append(data)

    WeighingApp.filter_list(app)

    assert calls == {"clear": 0, "update": [["   "]]}


def test_update_list_handles_empty_and_populated_lists():
    class ListboxStub:
        def __init__(self):
            self.deleted = []
            self.items = []

        def delete(self, *args):
            self.deleted.append(args)
            self.items = []

        def insert(self, _idx, value):
            self.items.append(value)

    app = type("Dummy", (), {})()
    app.listbox = ListboxStub()

    WeighingApp.update_list(app, [])
    assert app.visible_participants == []
    assert app.listbox.items == ["kein Teilnehmer gefunden"]

    participants = [{"Name": "Ada"}, {"Name": "Grace"}]
    WeighingApp.update_list(app, participants)
    assert app.visible_participants == participants
    assert app.listbox.items == ["  Ada", "  Grace"]


def test_on_select_ignores_invalid_and_shows_valid_selection():
    class ListboxStub:
        def __init__(self, selection):
            self.selection = selection

        def curselection(self):
            return self.selection

    app = type("Dummy", (), {})()
    shown = []
    app.visible_participants = [{"Name": "Ada"}]
    app.show_details = lambda participant: shown.append(participant)

    app.listbox = ListboxStub(())
    WeighingApp.on_select(app, None)
    assert shown == []

    app.listbox = ListboxStub((5,))
    WeighingApp.on_select(app, None)
    assert shown == []

    app.listbox = ListboxStub((0,))
    WeighingApp.on_select(app, None)
    assert app.selected_participant == {"Name": "Ada"}
    assert shown == [{"Name": "Ada"}]


def test_load_data_handles_empty_missing_and_valid_file(tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr("gui.messagebox.showerror", lambda title, msg: errors.append((title, msg)))

    app = type("Dummy", (), {})()
    updates = []
    app.update_list = lambda data: updates.append(list(data))

    app.data_file_path = ""
    WeighingApp.load_data(app)
    assert app.participants == []
    assert updates[-1] == []

    app.data_file_path = str(tmp_path / "missing.json")
    WeighingApp.load_data(app)
    assert errors[-1][0] == "Error"
    assert "Data file not found" in errors[-1][1]

    valid_file = tmp_path / "participants.json"
    valid_file.write_text(json.dumps({"participants": [{"Name": "Ada"}, "x", {"Name": "Grace"}]}), encoding="utf-8")
    app.data_file_path = str(valid_file)
    WeighingApp.load_data(app)

    assert app.participants == [{"Name": "Ada"}, {"Name": "Grace"}]
    assert updates[-1] == [{"Name": "Ada"}, {"Name": "Grace"}]


def test_prompt_for_data_source_selection_only_runs_when_needed(monkeypatch):
    infos = []
    monkeypatch.setattr("gui.messagebox.showinfo", lambda title, msg: infos.append((title, msg)))

    app = type("Dummy", (), {})()
    opens = []
    app.open_settings_window = lambda: opens.append(True)
    app.data_file_path = ""

    WeighingApp.prompt_for_data_source_selection(app)
    assert infos == [("Achtung", "Bitte Datenquelle auswählen.")]
    assert opens == [True]

    app.data_file_path = "already-set.json"
    WeighingApp.prompt_for_data_source_selection(app)
    assert infos == [("Achtung", "Bitte Datenquelle auswählen.")]
    assert opens == [True]


def test_show_details_populates_fields_and_normalizes_flags():
    app = type("Dummy", (), {})()
    app.val_prename = DummyField()
    app.val_surname = DummyField()
    app.val_birthyear = DummyField()
    app.val_club = DummyField()
    app.weight_var = DummyField()
    app.valid_var = DummyVar()
    app.paid_var = DummyVar()
    app.gender_var = DummyVar()
    app.get_birth_year_text = lambda participant: WeighingApp.get_birth_year_text(participant)
    app.to_bool = lambda value: WeighingApp.to_bool(value)
    updates = []
    app.update_status_dropdown_colors = lambda: updates.append(True)

    participant = {
        "Name": "Ada Lovelace",
        "Firstname": "Ada",
        "Birthyear": 1815,
        "Club": "TOP",
        WEIGHT_KEY: 75.4,
        VALID_KEY: "ja",
        "Paid": True,
        "Gender": "m",
    }

    WeighingApp.show_details(app, participant)

    assert app.val_prename.value == "Ada"
    assert app.val_surname.value == "Lovelace"
    assert app.val_birthyear.value == "1815"
    assert app.val_club.value == "TOP"
    assert app.weight_var.value == "75.4"
    assert app.valid_var.value == "gueltig"
    assert app.paid_var.value == PAID
    assert app.gender_var.value == "maennlich"
    assert updates == [True]


def test_save_data_writes_json(tmp_path):
    app = type("Dummy", (), {})()
    app.data_file_path = str(tmp_path / "out.json")
    app.participants = [{"Name": "Ada"}]

    WeighingApp.save_data(app)

    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8")) == [{"Name": "Ada"}]


def test_read_scale_with_pending_weight_shows_existing_popup():
    app = type("Dummy", (), {})()
    app.pending_received_weight = 7564
    seen = []
    app.show_weight_popup = lambda weight: seen.append(weight)

    WeighingApp.read_scale(app)

    assert seen == [7564]


def test_trigger_qr_scan_hotkey_success_and_failure(monkeypatch):
    pressed = []
    monkeypatch.setattr(gui, "keyboard", type("Keyboard", (), {"press_and_release": lambda key: pressed.append(key)}))

    app = type("Dummy", (), {})()
    WeighingApp.trigger_qr_scan_hotkey(app)
    assert pressed == ["F12"]

    errors = []
    monkeypatch.setattr("gui.messagebox.showerror", lambda title, msg: errors.append((title, msg)))

    class BrokenKeyboard:
        @staticmethod
        def press_and_release(_key):
            raise RuntimeError("broken")

    monkeypatch.setattr(gui, "keyboard", BrokenKeyboard)
    WeighingApp.trigger_qr_scan_hotkey(app)
    assert errors == [("QR Scan", "F12 konnte nicht ausgelost werden: broken")]


def test_apply_received_weight_and_close_popup():
    app = type("Dummy", (), {})()
    shown = []
    app.show_weight_popup = lambda weight: shown.append(weight)

    WeighingApp.apply_received_weight(app, 7564)
    assert app.pending_received_weight == 7564
    assert shown == [7564]

    class Popup:
        def __init__(self):
            self.destroyed = False

        def winfo_exists(self):
            return True

        def destroy(self):
            self.destroyed = True

    popup = Popup()
    app.weight_popup = popup
    app.weight_popup_name_label = object()
    app.weight_popup_value_label = object()

    WeighingApp.close_weight_popup(app)
    assert popup.destroyed is True
    assert app.weight_popup is None
    assert app.weight_popup_name_label is None
    assert app.weight_popup_value_label is None


def test_send_ws_payload_and_broadcast_remove_stale_clients(monkeypatch):
    scheduled = []

    def fake_run_coroutine_threadsafe(coro, loop):
        scheduled.append((coro, loop))
        coro.close()
        return object()

    monkeypatch.setattr("gui.asyncio.run_coroutine_threadsafe", fake_run_coroutine_threadsafe)

    app = type("Dummy", (), {})()
    app.ws_loop = object()
    app.ws_clients = {object()}
    app._broadcast_payload = lambda payload: asyncio.sleep(0)

    WeighingApp.send_ws_payload(app, {"type": "PING"})
    assert len(scheduled) == 1
    assert scheduled[0][1] is app.ws_loop

    app.ws_loop = None
    WeighingApp.send_ws_payload(app, {"type": "IGNORED"})
    assert len(scheduled) == 1

    sent = []

    class GoodClient:
        async def send(self, msg):
            sent.append(msg)

    class BadClient:
        async def send(self, _msg):
            raise RuntimeError("gone")

    app.ws_clients = {GoodClient(), BadClient()}
    asyncio.run(WeighingApp._broadcast_payload(app, {"text": "ä"}))

    assert sent == ['{"text": "ä"}']
    assert len(app.ws_clients) == 1


def test_on_close_calls_shutdown_steps():
    app = type("Dummy", (), {})()
    calls = []
    app.close_weight_popup = lambda: calls.append("close_weight_popup")
    app.stop_websocket_server = lambda: calls.append("stop_websocket_server")
    app.destroy = lambda: calls.append("destroy")

    WeighingApp.on_close(app)

    assert calls == ["close_weight_popup", "stop_websocket_server", "destroy"]


def test_start_websocket_server_handles_missing_module_running_thread_and_new_thread(monkeypatch):
    warnings = []
    monkeypatch.setattr("gui.messagebox.showwarning", lambda title, msg: warnings.append((title, msg)))

    app = type("Dummy", (), {})()
    app.ws_thread = None
    original_websockets = gui.websockets
    monkeypatch.setattr(gui, "websockets", None)
    WeighingApp.start_websocket_server(app)
    assert warnings and warnings[-1][0] == "WebSocket"

    monkeypatch.setattr(gui, "websockets", original_websockets)

    class AliveThread:
        def is_alive(self):
            return True

    app.ws_thread = AliveThread()
    WeighingApp.start_websocket_server(app)

    started = []

    class FakeThread:
        def __init__(self, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self):
            started.append((self.target, self.daemon))

        def is_alive(self):
            return False

    monkeypatch.setattr("gui.threading.Thread", FakeThread)
    app.ws_thread = None
    app._run_websocket_loop = lambda: None
    WeighingApp.start_websocket_server(app)

    assert started == [(app._run_websocket_loop, True)]


def test_run_websocket_loop_and_start_ws_server(monkeypatch):
    class Task:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    task = Task()
    server = object()

    class FakeLoop:
        def __init__(self):
            self.closed = False
            self.run_until_complete_calls = []
            self.forever_called = False

        def run_until_complete(self, arg):
            self.run_until_complete_calls.append(arg)
            return server

        def run_forever(self):
            self.forever_called = True

        def close(self):
            self.closed = True

    loop = FakeLoop()
    app = type("Dummy", (), {})()
    app._start_ws_server = lambda: "start-coro"

    monkeypatch.setattr("gui.asyncio.new_event_loop", lambda: loop)
    monkeypatch.setattr("gui.asyncio.set_event_loop", lambda _loop: None)
    monkeypatch.setattr("gui.asyncio.all_tasks", lambda _loop: {task})
    monkeypatch.setattr("gui.asyncio.gather", lambda *args, **kwargs: "gather-coro")

    WeighingApp._run_websocket_loop(app)

    assert app.ws_loop is loop
    assert app.ws_server is server
    assert loop.run_until_complete_calls == ["start-coro", "gather-coro"]
    assert loop.forever_called is True
    assert loop.closed is True
    assert task.cancelled is True

    async def _run():
        called = []

        async def fake_serve(handler, host, port):
            called.append((handler, host, port))
            return "server"

        monkeypatch.setattr(gui.websockets, "serve", fake_serve)
        result = await WeighingApp._start_ws_server(app)
        assert result == "server"
        assert called == [(app._ws_handler, gui.WS_HOST, gui.WS_PORT)]

    app._ws_handler = object()
    asyncio.run(_run())


def test_show_weight_popup_creates_and_updates_popup(monkeypatch):
    created_buttons = []

    class FakePopup:
        def __init__(self, _parent=None, **_kwargs):
            self.exists = True
            self.deiconified = False
            self.lifted = False
            self.geometry_calls = []

        def title(self, _value):
            return None

        def geometry(self, value):
            self.geometry_calls.append(value)

        def configure(self, **_kwargs):
            return None

        def resizable(self, *_args):
            return None

        def transient(self, _parent):
            return None

        def protocol(self, *_args):
            return None

        def update_idletasks(self):
            return None

        def winfo_exists(self):
            return self.exists

        def winfo_screenwidth(self):
            return 1200

        def winfo_screenheight(self):
            return 800

        def deiconify(self):
            self.deiconified = True

        def lift(self):
            self.lifted = True

    class FakeLabel(ConfigRecorder):
        def __init__(self, _parent=None, **kwargs):
            super().__init__()
            self.text = kwargs.get("text")

        def pack(self, **_kwargs):
            return None

        def config(self, **kwargs):
            super().config(**kwargs)
            if "text" in kwargs:
                self.text = kwargs["text"]

    class FakeFrame:
        def __init__(self, _parent=None, **_kwargs):
            return None

        def pack(self, **_kwargs):
            return None

    class FakeButton:
        def __init__(self, _parent=None, **kwargs):
            self.kwargs = kwargs
            created_buttons.append(kwargs)

        def pack(self, **_kwargs):
            return None

    monkeypatch.setattr("gui.tk.Toplevel", FakePopup)
    monkeypatch.setattr("gui.tk.Label", FakeLabel)
    monkeypatch.setattr("gui.tk.Frame", FakeFrame)
    monkeypatch.setattr("gui.tk.Button", FakeButton)

    app = type("Dummy", (), {})()
    app.weight_popup = None
    app.weight_popup_name_label = None
    app.weight_popup_value_label = None
    app.get_selected_full_name = lambda: "Lovelace, Ada"
    app.format_scale_weight = lambda weight: f"{weight/100:.2f}"
    app.accept_pending_weight = lambda: None
    app.cancel_pending_weight = lambda: None
    app.update_idletasks = lambda: None
    app.winfo_rootx = lambda: 10
    app.winfo_rooty = lambda: 20
    app.winfo_width = lambda: 1000
    app.winfo_height = lambda: 700

    WeighingApp.show_weight_popup(app, 7564)

    assert isinstance(app.weight_popup, FakePopup)
    assert app.weight_popup_name_label.text == "Lovelace, Ada"
    assert app.weight_popup_value_label.text == "75.64 kg"
    assert [b["text"] for b in created_buttons] == ["OK", "Cancel"]

    app.get_selected_full_name = lambda: "Hopper, Grace"
    WeighingApp.show_weight_popup(app, 8000)

    assert app.weight_popup_name_label.text == "Hopper, Grace"
    assert app.weight_popup_value_label.text == "80.00 kg"
    assert app.weight_popup.deiconified is True
    assert app.weight_popup.lifted is True


def test_open_settings_window_loads_file_and_saves(tmp_path, monkeypatch):
    created_buttons = []

    class FakePopup:
        def __init__(self, _parent=None, **_kwargs):
            self.destroyed = False

        def title(self, _value):
            return None

        def geometry(self, _value):
            return None

        def configure(self, **_kwargs):
            return None

        def resizable(self, *_args):
            return None

        def destroy(self):
            self.destroyed = True

        def winfo_exists(self):
            return True

    class FakeStringVar(DummyVar):
        pass

    class FakeMenu:
        def __init__(self):
            self.config_calls = []

        def config(self, **kwargs):
            self.config_calls.append(kwargs)

    class FakeOptionMenu:
        def __init__(self, _parent, variable, *values):
            self.variable = variable
            self.values = values
            self.menu = FakeMenu()
            self.config_calls = []

        def config(self, **kwargs):
            self.config_calls.append(kwargs)

        def __getitem__(self, key):
            if key == "menu":
                return self.menu
            raise KeyError(key)

        def pack(self, **_kwargs):
            return None

    class FakeLabel(ConfigRecorder):
        def __init__(self, _parent=None, **kwargs):
            super().__init__()
            self.text = kwargs.get("text")

        def pack(self, **_kwargs):
            return None

        def config(self, **kwargs):
            super().config(**kwargs)
            if "text" in kwargs:
                self.text = kwargs["text"]

    class FakeFrame:
        def __init__(self, _parent=None, **_kwargs):
            return None

        def pack(self, **_kwargs):
            return None

    class FakeButton:
        def __init__(self, _parent=None, **kwargs):
            self.kwargs = kwargs
            created_buttons.append(self)

        def pack(self, **_kwargs):
            return None

    monkeypatch.setattr("gui.tk.Toplevel", FakePopup)
    monkeypatch.setattr("gui.tk.StringVar", FakeStringVar)
    monkeypatch.setattr("gui.tk.OptionMenu", FakeOptionMenu)
    monkeypatch.setattr("gui.tk.Label", FakeLabel)
    monkeypatch.setattr("gui.tk.Frame", FakeFrame)
    monkeypatch.setattr("gui.tk.Button", FakeButton)

    data_file = tmp_path / "participants.json"
    data_file.write_text(json.dumps([{"Name": "Ada"}]), encoding="utf-8")
    monkeypatch.setattr("gui.filedialog.askopenfilename", lambda **_kwargs: str(data_file))

    app = type("Dummy", (), {})()
    app.weight_decimal_places = 2
    app.data_file_path = ""
    app.pending_received_weight = 7564
    app.weight_popup = FakePopup()
    loaded = []
    shown = []
    app.load_data = lambda: loaded.append(app.data_file_path)
    app.show_weight_popup = lambda weight: shown.append(weight)

    WeighingApp.open_settings_window(app)

    by_text = {button.kwargs["text"]: button for button in created_buttons}
    by_text["Daten laden"].kwargs["command"]()
    by_text["Save"].kwargs["command"]()

    assert loaded == [str(data_file)]
    assert app.data_file_path == str(data_file)
    assert app.weight_decimal_places == 2
    assert shown == [7564]


def test_prompt_birth_year_correction_handles_invalid_then_valid_input(monkeypatch):
    created_entries = []
    created_buttons = []
    errors = []

    class FakeParent:
        def update_idletasks(self):
            return None

        def winfo_rootx(self):
            return 100

        def winfo_rooty(self):
            return 200

        def winfo_width(self):
            return 800

        def winfo_height(self):
            return 600

    class FakePopup:
        def __init__(self, _parent=None, **_kwargs):
            self.destroyed = False
            self.bound = []
            self.protocol_calls = []

        def title(self, _value):
            return None

        def geometry(self, _value):
            return None

        def configure(self, **_kwargs):
            return None

        def resizable(self, *_args):
            return None

        def transient(self, _parent):
            return None

        def update_idletasks(self):
            return None

        def grab_set(self):
            return None

        def grab_release(self):
            return None

        def bind(self, event, callback):
            self.bound.append((event, callback))

        def protocol(self, name, callback):
            self.protocol_calls.append((name, callback))

        def winfo_screenwidth(self):
            return 1200

        def winfo_screenheight(self):
            return 800

        def destroy(self):
            self.destroyed = True

        def wait_window(self):
            entry = created_entries[-1]
            entry.value = "bad"
            created_buttons[-1].kwargs["command"]()
            entry.value = "2015"
            created_buttons[-1].kwargs["command"]()

    class FakeLabel:
        def __init__(self, _parent=None, **_kwargs):
            return None

        def pack(self, **_kwargs):
            return None

    class FakeEntry(DummyField):
        def __init__(self, _parent=None, **_kwargs):
            super().__init__("")
            self.config_calls = []
            self.bound = []
            self.focused = 0
            self.selection_calls = []
            created_entries.append(self)

        def pack(self, **_kwargs):
            return None

        def config(self, **kwargs):
            self.config_calls.append(kwargs)

        def bind(self, event, callback):
            self.bound.append((event, callback))

        def focus_set(self):
            self.focused += 1

        def selection_range(self, start, end):
            self.selection_calls.append((start, end))

    class FakeButton:
        def __init__(self, _parent=None, **kwargs):
            self.kwargs = kwargs
            created_buttons.append(self)

        def pack(self, **_kwargs):
            return None

    monkeypatch.setattr("gui.tk.Toplevel", FakePopup)
    monkeypatch.setattr("gui.tk.Label", FakeLabel)
    monkeypatch.setattr("gui.tk.Entry", FakeEntry)
    monkeypatch.setattr("gui.tk.Button", FakeButton)
    monkeypatch.setattr("gui.messagebox.showerror", lambda title, msg, parent=None: errors.append((title, msg, parent)))

    app = type("Dummy", (), {})()
    year = WeighingApp.prompt_birth_year_correction(app, FakeParent(), "")

    assert year == 2015
    assert len(errors) == 1
    assert errors[0][0] == "Fehler"
    assert "Geburtsjahr falsch" in errors[0][1]
    assert created_entries[-1].selection_calls[-1] == (0, gui.tk.END)


def test_open_add_participant_window_reuses_existing_and_handles_close(monkeypatch):
    created_entries = []
    created_buttons = []
    created_radios = []

    class ExistingPopup:
        def __init__(self):
            self.lifted = False
            self.focused = False

        def winfo_exists(self):
            return True

        def lift(self):
            self.lifted = True

        def focus_force(self):
            self.focused = True

    app = type("Dummy", (), {})()
    existing = ExistingPopup()
    app.add_participant_popup = existing
    app.add_participant_fields = {}

    WeighingApp.open_add_participant_window(app)
    assert existing.lifted is True
    assert existing.focused is True

    class FakePopup:
        def __init__(self, _parent=None, **_kwargs):
            self.protocol_calls = []
            self.destroyed = False

        def title(self, _value):
            return None

        def geometry(self, _value):
            return None

        def configure(self, **_kwargs):
            return None

        def protocol(self, name, callback):
            self.protocol_calls.append((name, callback))

        def destroy(self):
            self.destroyed = True

        def winfo_exists(self):
            return True

        def lift(self):
            return None

        def focus_force(self):
            return None

    class FakeLabel:
        def __init__(self, _parent=None, **_kwargs):
            return None

        def pack(self, **_kwargs):
            return None

    class FakeEntry(DummyField):
        def __init__(self, _parent=None, **_kwargs):
            super().__init__("")
            self.focused = False
            created_entries.append(self)

        def pack(self, **_kwargs):
            return None

        def focus_set(self):
            self.focused = True

    class FakeStringVar(DummyVar):
        pass

    class FakeFrame:
        def __init__(self, _parent=None, **_kwargs):
            return None

        def pack(self, **_kwargs):
            return None

    class FakeRadio:
        def __init__(self, _parent=None, **kwargs):
            self.kwargs = kwargs
            created_radios.append(self)

        def pack(self, **_kwargs):
            return None

    class FakeButton:
        def __init__(self, _parent=None, **kwargs):
            self.kwargs = kwargs
            created_buttons.append(self)

        def pack(self, **_kwargs):
            return None

    monkeypatch.setattr("gui.tk.Toplevel", FakePopup)
    monkeypatch.setattr("gui.tk.Label", FakeLabel)
    monkeypatch.setattr("gui.tk.Entry", FakeEntry)
    monkeypatch.setattr("gui.tk.StringVar", FakeStringVar)
    monkeypatch.setattr("gui.tk.Frame", FakeFrame)
    monkeypatch.setattr("gui.tk.Radiobutton", FakeRadio)
    monkeypatch.setattr("gui.tk.Button", FakeButton)

    saved = []
    app.add_participant_popup = None
    app.save_new_participant = lambda popup, e_first, e_last, e_club, e_birthyear, gender_var: saved.append(
        (popup, e_first, e_last, e_club, e_birthyear, gender_var)
    )
    app.fill_add_participant_from_qr = lambda qr_data: WeighingApp.fill_add_participant_from_qr(app, qr_data)

    WeighingApp.open_add_participant_window(app)

    popup = app.add_participant_popup
    assert popup is not None
    assert set(app.add_participant_fields) == {"e_first", "e_last", "e_club", "e_birthyear", "gender_var"}
    assert len(created_entries) == 4
    assert [radio.kwargs["text"] for radio in created_radios] == ["maennlich", "weiblich"]

    by_text = {button.kwargs["text"]: button for button in created_buttons}
    by_text["Save"].kwargs["command"]()
    assert len(saved) == 1
    assert saved[0][0] is popup

    app.add_participant_fields["e_first"].insert(0, "Ada")
    app.add_participant_fields["e_last"].insert(0, "Lovelace")
    app.add_participant_fields["e_birthyear"].insert(0, "1815")
    WeighingApp.fill_add_participant_from_qr(
        app,
        {"first_name": "Grace", "last_name": "Hopper", "birth_year": 1906},
    )
    assert app.add_participant_fields["e_first"].value == "Grace"
    assert app.add_participant_fields["e_last"].value == "Hopper"
    assert app.add_participant_fields["e_birthyear"].value == "1906"
    assert app.add_participant_fields["e_first"].focused is True

    WeighingApp.handle_incoming_qr(app, {"name": "Grace Hopper", "first_name": "Grace", "last_name": "Hopper"})
    assert app.add_participant_fields["e_first"].value == "Grace"

    popup.protocol_calls[0][1]()
    assert app.add_participant_popup is None
    assert app.add_participant_fields == {}
    assert popup.destroyed is True


def test_handle_incoming_qr_without_popup_uses_search():
    app = type("Dummy", (), {})()
    app.add_participant_popup = None
    seen = []
    app.apply_qr_search = lambda name: seen.append(name)

    WeighingApp.handle_incoming_qr(app, {"name": "Ada Lovelace"})

    assert seen == ["Ada Lovelace"]


def test_create_layout_builds_expected_core_widgets(monkeypatch):
    class FakeVar(DummyVar):
        pass

    class FakeFrame:
        def __init__(self, _parent=None, **kwargs):
            self.kwargs = kwargs
            self.pack_calls = []
            self.grid_calls = []
            self.columnconfigure_calls = []

        def pack(self, **kwargs):
            self.pack_calls.append(kwargs)

        def pack_propagate(self, value):
            self.pack_propagate_value = value

        def grid(self, **kwargs):
            self.grid_calls.append(kwargs)

        def columnconfigure(self, idx, weight):
            self.columnconfigure_calls.append((idx, weight))

    class FakeEntry(DummyField):
        def __init__(self, _parent=None, **kwargs):
            super().__init__("")
            self.kwargs = kwargs
            self.pack_calls = []
            self.grid_calls = []
            self.bound = []

        def pack(self, **kwargs):
            self.pack_calls.append(kwargs)

        def grid(self, **kwargs):
            self.grid_calls.append(kwargs)

        def bind(self, event, callback):
            self.bound.append((event, callback))

    class FakeScrollbar:
        def __init__(self, _parent=None, **_kwargs):
            self.pack_calls = []
            self.config_calls = []

        def pack(self, **kwargs):
            self.pack_calls.append(kwargs)

        def config(self, **kwargs):
            self.config_calls.append(kwargs)

        def set(self, *_args):
            return None

    class FakeListbox:
        def __init__(self, _parent=None, **kwargs):
            self.kwargs = kwargs
            self.pack_calls = []
            self.bound = []

        def pack(self, **kwargs):
            self.pack_calls.append(kwargs)

        def bind(self, event, callback):
            self.bound.append((event, callback))

        def yview(self, *_args):
            return None

    class FakeLabel:
        def __init__(self, _parent=None, **kwargs):
            self.kwargs = kwargs
            self.pack_calls = []
            self.grid_calls = []
            self.bound = []

        def pack(self, **kwargs):
            self.pack_calls.append(kwargs)

        def grid(self, **kwargs):
            self.grid_calls.append(kwargs)

        def bind(self, event, callback):
            self.bound.append((event, callback))

    monkeypatch.setattr("gui.tk.Frame", FakeFrame)
    monkeypatch.setattr("gui.tk.StringVar", FakeVar)
    monkeypatch.setattr("gui.tk.Entry", FakeEntry)
    monkeypatch.setattr("gui.tk.Scrollbar", FakeScrollbar)
    monkeypatch.setattr("gui.tk.Listbox", FakeListbox)
    monkeypatch.setattr("gui.tk.Label", FakeLabel)

    app = type("Dummy", (), {})()
    label_calls = []
    entry_calls = []
    dropdown_calls = []
    action_buttons = []
    color_updates = []
    app.filter_list = lambda *args: None
    app.on_select = lambda _event: None
    app.create_action_buttons = lambda: action_buttons.append(True)
    app.create_label = lambda parent, text, r, c: label_calls.append((text, r, c))
    app.create_entry_value = lambda parent, r, c: entry_calls.append((r, c)) or DummyField()
    app.create_status_dropdown = (
        lambda parent, variable, options, r, c: dropdown_calls.append((tuple(options), r, c)) or ConfigRecorder()
    )
    app.update_status_dropdown_colors = lambda *args: color_updates.append(True)
    app.trigger_qr_scan_hotkey = lambda _event=None: None

    WeighingApp.create_layout(app)

    assert action_buttons == [True]
    assert len(label_calls) == 8
    assert len(entry_calls) == 5
    assert dropdown_calls == [
        (("maennlich", "weiblich"), 5, 1),
        (("gueltig", "ungueltig"), 7, 0),
        ((PAID, UNPAID), 7, 1),
    ]
    assert isinstance(app.search_var, FakeVar)
    assert isinstance(app.valid_var, FakeVar)
    assert isinstance(app.paid_var, FakeVar)
    assert isinstance(app.gender_var, FakeVar)
    assert color_updates == [True]
