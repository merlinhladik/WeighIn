import asyncio
import json

from gui import BIRTHYEAR_KEY, PAID_KEY, VALID_KEY, WEIGHT_KEY, WeighingApp


def test_init_sets_defaults_and_calls_bootstrap_steps(monkeypatch):
    calls = []
    protocol_calls = []

    monkeypatch.setattr("tkinter.Tk.__init__", lambda self: None)
    monkeypatch.setattr(WeighingApp, "title", lambda self, _v: None)
    monkeypatch.setattr(WeighingApp, "geometry", lambda self, _v: None)
    monkeypatch.setattr(WeighingApp, "configure", lambda self, **_kwargs: None)
    monkeypatch.setattr(
        WeighingApp,
        "protocol",
        lambda self, name, callback: protocol_calls.append((name, callback)),
    )
    monkeypatch.setattr(WeighingApp, "create_layout", lambda self: calls.append("create_layout"))
    monkeypatch.setattr(WeighingApp, "load_settings", lambda self: calls.append("load_settings"))
    monkeypatch.setattr(WeighingApp, "load_data", lambda self: calls.append("load_data"))
    monkeypatch.setattr(
        WeighingApp,
        "prompt_for_data_source_selection",
        lambda self: calls.append("prompt_for_data_source_selection"),
    )
    monkeypatch.setattr(
        WeighingApp, "start_websocket_server", lambda self: calls.append("start_websocket_server")
    )

    app = WeighingApp()

    assert app.participants == []
    assert app.selected_participant is None
    assert app.pending_received_weight is None
    assert app.weight_decimal_places == 0
    assert app.weight_popup is None
    assert app.ws_loop is None
    assert app.ws_thread is None
    assert app.ws_server is None
    assert app.ws_clients == set()

    assert calls == [
        "create_layout",
        "load_settings",
        "load_data",
        "start_websocket_server",
        "prompt_for_data_source_selection",
    ]
    assert len(protocol_calls) == 1
    assert protocol_calls[0][0] == "WM_DELETE_WINDOW"
    assert callable(protocol_calls[0][1])


def test_to_bool_variants():
    assert WeighingApp.to_bool(True) is True
    assert WeighingApp.to_bool(False) is False
    assert WeighingApp.to_bool("ja") is True
    assert WeighingApp.to_bool("1") is True
    assert WeighingApp.to_bool("no") is False
    assert WeighingApp.to_bool(None) is False


def test_parse_birth_year():
    assert WeighingApp.parse_birth_year("2010") == 2010
    assert WeighingApp.parse_birth_year(" 2010 ") == 2010
    assert WeighingApp.parse_birth_year("20a0") is None
    assert WeighingApp.parse_birth_year("100") is None
    assert WeighingApp.parse_birth_year("abc") is None


def test_format_scale_weight():
    dummy = type("Dummy", (), {"weight_decimal_places": 2})()
    assert WeighingApp.format_scale_weight(dummy, 7564) == "75.64"


def test_filter_qr_alias_fields():
    dummy = object()
    out = WeighingApp.filter_qr(dummy, {"first": "Ada", "last": "Lovelace", "exp_timestamp": 123})

    assert out["name"] == "Ada Lovelace"
    assert out["exp_timestamp"] == 123


def test_filter_qr_non_dict_returns_empty_payload():
    out = WeighingApp.filter_qr(object(), "not-a-dict")
    assert out == {
        "name": "",
        "first_name": "",
        "last_name": "",
        "birth_year": 0,
        "exp_timestamp": None,
    }


def test_get_birth_year_text_uses_year():
    participant = {BIRTHYEAR_KEY: 2013}
    assert WeighingApp.get_birth_year_text(participant) == "2013"


def test_get_birth_year_text_returns_placeholder():
    assert WeighingApp.get_birth_year_text({}) == "---"


def test_fix_mojibake_text_keeps_value_if_repair_fails():
    value = "MÃƒÂ¼ller"
    assert WeighingApp.fix_mojibake_text(value) == value


def test_fix_mojibake_text_ignores_non_string():
    assert WeighingApp.fix_mojibake_text(123) == 123


def test_format_scale_weight_falls_back_for_invalid_places():
    dummy = type("Dummy", (), {"weight_decimal_places": 9})()
    assert WeighingApp.format_scale_weight(dummy, 7564) == "756.4"


def test_get_filtered_participants_by_name_and_club():
    app = type("Dummy", (), {})()
    app.participants = [
        {"Name": "Ada Lovelace", "Verein": "TOP"},
        {"Name": "Max Muster", "Verein": "Judo Club"},
    ]
    app.search_participants = lambda query: WeighingApp.search_participants(app, query)

    by_name = WeighingApp.get_filtered_participants(app, "ada")
    by_club = WeighingApp.get_filtered_participants(app, "judo")
    empty_query = WeighingApp.get_filtered_participants(app, "")

    assert by_name == [app.participants[0]]
    assert by_club == [app.participants[1]]
    assert empty_query == app.participants


def test_get_exact_name_matches_supports_fallback_name():
    app = type("Dummy", (), {})()
    app.participants = [
        {"Firstname": "Ada", "Lastname": "Lovelace"},
        {"Name": "Ada Lovelace"},
        {"Firstname": "Max", "Lastname": "Muster"},
    ]

    out = WeighingApp.get_exact_name_matches(app, "Ada   Lovelace")
    assert len(out) == 2


def test_get_selected_full_name_with_and_without_selection():
    app = type("Dummy", (), {})()
    app.selected_participant = {"Firstname": "Ada", "Lastname": "Lovelace"}
    assert WeighingApp.get_selected_full_name(app) == "Lovelace, Ada"

    app.selected_participant = None
    assert WeighingApp.get_selected_full_name(app) == "Keine Person ausgewahlt"


class DummyField:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def delete(self, *_args):
        self.value = ""

    def insert(self, _idx, value):
        self.value = value


def test_save_weight_without_selection_shows_warning(monkeypatch):
    calls = []
    monkeypatch.setattr("gui.messagebox.showwarning", lambda title, msg: calls.append((title, msg)))

    app = type("Dummy", (), {})()
    app.selected_participant = None

    WeighingApp.save_weight(app)

    assert calls == [("No selection", "Please select a participant first.")]


def test_save_weight_invalid_weight_shows_error(monkeypatch):
    errors = []
    monkeypatch.setattr("gui.messagebox.showerror", lambda title, msg: errors.append((title, msg)))

    app = type("Dummy", (), {})()
    app.selected_participant = {"ID": 1}
    app.weight_var = DummyField("abc")

    WeighingApp.save_weight(app)

    assert errors == [("Fehler", "ungültiges Gewicht. Bitte ausschließlich Nummern eingeben")]


def test_save_weight_success_updates_participant_and_sends_payload(monkeypatch):
    infos = []
    monkeypatch.setattr("gui.messagebox.showinfo", lambda title, msg: infos.append((title, msg)))

    app = type("Dummy", (), {})()
    app.selected_participant = {
        "ID": 7,
        "Firstname": "Old",
        "Lastname": "Name",
        "Name": "Old Name",
        "Weight": 60,
        "Valid": True,
        "Paid": False,
    }
    app.participants = [app.selected_participant]
    app.weight_var = DummyField("75.4")
    app.val_prename = DummyField("Ada")
    app.val_surname = DummyField("Lovelace")
    app.val_birthyear = DummyField("2015")
    app.valid_var = DummyField("gueltig")
    app.paid_var = DummyField("Zahlung erfolgt")
    app.gender_var = DummyField("weiblich")
    calls = {"save_data": 0, "update_list": [], "payloads": []}
    app.save_data = lambda: calls.__setitem__("save_data", calls["save_data"] + 1)
    app.update_list = lambda data: calls["update_list"].append(data)
    app.send_ws_payload = lambda payload: calls["payloads"].append(payload)

    WeighingApp.save_weight(app)

    p = app.selected_participant
    assert p[WEIGHT_KEY] == 75.4
    assert p["Firstname"] == "Ada"
    assert p["Lastname"] == "Lovelace"
    assert p["Name"] == "Ada Lovelace"
    assert p[VALID_KEY] is True
    assert p[PAID_KEY] is True
    assert p["Gender"] == "w"
    assert p[BIRTHYEAR_KEY] == 2015
    assert "Gewicht" not in p
    assert "Gueltig" not in p

    assert calls["save_data"] == 1
    assert calls["update_list"] == [app.participants]
    assert len(calls["payloads"]) == 1
    payload = calls["payloads"][0]
    assert payload["type"] == "WEIGH_IN"
    assert payload["participant_id"] == 7
    assert payload["name"] == "Ada Lovelace"
    assert payload["weight"] == 75.4
    assert payload["valid"] is True
    assert payload["paid"] is True
    assert isinstance(payload["timestamp"], str) and payload["timestamp"]

    assert infos == [("Saved", "Updated: Ada Lovelace\nWeight: 75.4 kg")]


def test_save_weight_handles_save_exception(monkeypatch):
    errors = []
    monkeypatch.setattr("gui.messagebox.showerror", lambda title, msg: errors.append((title, msg)))

    app = type("Dummy", (), {})()
    app.selected_participant = {"ID": 1}
    app.participants = [app.selected_participant]
    app.weight_var = DummyField("70")
    app.val_prename = DummyField("Ada")
    app.val_surname = DummyField("Lovelace")
    app.val_birthyear = DummyField("2015")
    app.valid_var = DummyField("gueltig")
    app.paid_var = DummyField("Zahlung erfolgt")
    app.gender_var = DummyField("maennlich")
    app.save_data = lambda: (_ for _ in ()).throw(RuntimeError("disk full"))
    app.update_list = lambda _data: None
    app.send_ws_payload = lambda _payload: None

    WeighingApp.save_weight(app)

    assert len(errors) == 1
    assert errors[0][0] == "Error"
    assert errors[0][1] == "Could not save data: disk full"


def test_read_scale_requests_weight_from_connected_client():
    app = type("Dummy", (), {})()
    app.pending_received_weight = None
    app.ws_loop = object()
    app.ws_clients = {object()}
    sent = []
    app.send_ws_payload = lambda payload: sent.append(payload)

    WeighingApp.read_scale(app)

    assert sent == [{"type": "REQUEST_WEIGHT"}]


def test_read_scale_without_connected_client_shows_warning(monkeypatch):
    warnings = []
    monkeypatch.setattr("gui.messagebox.showwarning", lambda title, msg: warnings.append((title, msg)))

    app = type("Dummy", (), {})()
    app.pending_received_weight = None
    app.ws_loop = None
    app.ws_clients = set()

    WeighingApp.read_scale(app)

    assert warnings == [("Scale", "No scale client connected.")]


def test_accept_pending_weight_writes_entry_and_closes_popup():
    class EntryStub:
        def __init__(self):
            self.value = None

        def delete(self, *_args):
            return None

        def insert(self, _idx, value):
            self.value = value

    app = type("Dummy", (), {})()
    app.pending_received_weight = 7564
    app.weight_var = EntryStub()
    app.format_scale_weight = lambda value: f"{value/100:.2f}"
    closed = {"count": 0}
    saves = {"count": 0}
    app.close_weight_popup = lambda: closed.__setitem__("count", closed["count"] + 1)
    app.save_weight = lambda: saves.__setitem__("count", saves["count"] + 1)

    WeighingApp.accept_pending_weight(app)

    assert app.weight_var.value == "75.64"
    assert app.pending_received_weight is None
    assert saves["count"] == 1
    assert closed["count"] == 1


def test_cancel_pending_weight_clears_value_and_closes_popup():
    app = type("Dummy", (), {})()
    app.pending_received_weight = 7564
    closed = {"count": 0}
    app.close_weight_popup = lambda: closed.__setitem__("count", closed["count"] + 1)

    WeighingApp.cancel_pending_weight(app)

    assert app.pending_received_weight is None
    assert closed["count"] == 1


def test_create_action_buttons_builds_expected_widgets(monkeypatch):
    created_buttons = []
    created_labels = []

    class FakeFrame:
        def __init__(self, parent, **kwargs):
            self.parent = parent
            self.kwargs = kwargs
            self.place_forget_called = False

        def pack(self, **_kwargs):
            return None

        def place(self, **_kwargs):
            return None

        def lift(self):
            return None

        def place_forget(self):
            self.place_forget_called = True

    class FakeButton:
        def __init__(self, parent, **kwargs):
            self.parent = parent
            self.kwargs = kwargs
            self.place_calls = []
            self.lift_called = False
            created_buttons.append(self)

        def pack(self, **_kwargs):
            return None

        def place(self, **kwargs):
            self.place_calls.append(kwargs)

        def lift(self):
            self.lift_called = True

    class FakeLabel:
        def __init__(self, parent, **kwargs):
            self.parent = parent
            self.kwargs = kwargs
            created_labels.append(self)

        def pack(self, **_kwargs):
            return None

    monkeypatch.setattr("gui.tk.Frame", FakeFrame)
    monkeypatch.setattr("gui.tk.Button", FakeButton)
    monkeypatch.setattr("gui.tk.Label", FakeLabel)

    app = type("Dummy", (), {})()
    app.main_container = object()
    app.save_weight = lambda: None
    app.read_scale = lambda: None
    app.open_settings_window = lambda: None
    app.open_add_participant_window = lambda: None
    app.hide_duplicate_warning = lambda: None

    WeighingApp.create_action_buttons(app)

    texts = [b.kwargs.get("text") for b in created_buttons]
    assert "Save" in texts
    assert "take current weight" in texts
    assert "Einstellungen" in texts
    assert "+" in texts
    assert "x" in texts

    assert hasattr(app, "btn_add")
    assert app.btn_add.lift_called is False
    assert len(app.btn_add.place_calls) == 0
    assert app.btn_add.kwargs.get("width") == 18
    assert app.btn_add.kwargs.get("height") == 2
    assert app.duplicate_warning_label.kwargs["text"] == "Achtung: Mehrere Personen gefunden"
    assert app.duplicate_warning_frame.place_forget_called is True
    assert len(created_labels) >= 1


def test_apply_qr_search_empty_name_hides_warning_only():
    app = type("Dummy", (), {})()
    flags = {"hide": 0}
    app.hide_duplicate_warning = lambda: flags.__setitem__("hide", flags["hide"] + 1)

    WeighingApp.apply_qr_search(app, "   ")

    assert flags["hide"] == 1


def test_apply_qr_search_selects_first_match_and_shows_duplicate_warning():
    class DummySearchVar:
        def __init__(self):
            self.value = None

        def set(self, value):
            self.value = value

    class DummyListbox:
        def __init__(self):
            self.calls = []

        def selection_clear(self, *args):
            self.calls.append(("selection_clear", args))

        def selection_set(self, *args):
            self.calls.append(("selection_set", args))

        def activate(self, *args):
            self.calls.append(("activate", args))

        def see(self, *args):
            self.calls.append(("see", args))

    participants = [
        {"ID": 1, "Name": "Ada Lovelace", "Firstname": "Ada", "Lastname": "Lovelace"},
        {"ID": 2, "Name": "Ada Lovelace", "Firstname": "Ada", "Lastname": "Lovelace"},
    ]

    app = type("Dummy", (), {})()
    app.search_var = DummySearchVar()
    app.listbox = DummyListbox()
    app.selected_participant = None
    app.get_filtered_participants = lambda _query: participants
    app.get_exact_name_matches = lambda _query: participants
    app.updated = []
    app.shown = []
    app.details = []
    app.update_list = lambda data: app.updated.append(data)
    app.show_duplicate_warning = lambda: app.shown.append(True)
    app.hide_duplicate_warning = lambda: app.shown.append(False)
    app.show_details = lambda p: app.details.append(p)

    WeighingApp.apply_qr_search(app, "Ada Lovelace")

    assert app.search_var.value == "Ada Lovelace"
    assert app.updated == [participants]
    assert app.shown == [True]
    assert app.selected_participant == participants[0]
    assert app.details == [participants[0]]
    assert any(call[0] == "selection_set" for call in app.listbox.calls)


def test_load_settings_defaults_when_file_missing(monkeypatch):
    app = type("Dummy", (), {})()
    app.weight_decimal_places = 3
    app.data_file_path = "x"

    WeighingApp.load_settings(app)

    assert app.weight_decimal_places == 0
    assert app.data_file_path == ""


def test_load_settings_reads_valid_values(monkeypatch):
    app = type("Dummy", (), {})()
    app.weight_decimal_places = 1
    app.data_file_path = "old.json"

    WeighingApp.load_settings(app)

    assert app.weight_decimal_places == 0
    assert app.data_file_path == ""


def test_load_settings_ignores_invalid_values(monkeypatch):
    app = type("Dummy", (), {})()
    app.weight_decimal_places = 2
    app.data_file_path = "old.json"

    WeighingApp.load_settings(app)

    assert app.weight_decimal_places == 0
    assert app.data_file_path == ""


def test_save_new_participant_warns_on_missing_names(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        "gui.messagebox.showwarning",
        lambda title, msg, parent=None: warnings.append((title, msg, parent)),
    )

    app = type("Dummy", (), {})()
    app.participants = []
    popup = type("Popup", (), {})()
    WeighingApp.save_new_participant(
        app,
        popup,
        DummyField(""),
        DummyField(""),
        DummyField("Club"),
        DummyField("2010"),
        DummyField("maennlich"),
    )

    assert len(warnings) == 1
    assert warnings[0][0] == "Missing fields"


def test_save_new_participant_invalid_birthyear_uses_correction_prompt(monkeypatch):
    infos = []
    monkeypatch.setattr("gui.messagebox.showinfo", lambda title, msg: infos.append((title, msg)))

    class Popup:
        def __init__(self):
            self.destroy_called = False

        def destroy(self):
            self.destroy_called = True

    app = type("Dummy", (), {})()
    app.participants = []
    app.add_participant_popup = None
    app.add_participant_fields = {}
    app.save_data = lambda: None
    app.update_list = lambda _data: None
    app.prompt_birth_year_correction = lambda _popup, txt: 2014
    popup = Popup()
    birthyear = DummyField("bad-year")
    WeighingApp.save_new_participant(
        app,
        popup,
        DummyField("Ada"),
        DummyField("Lovelace"),
        DummyField("Club"),
        birthyear,
        DummyField("weiblich"),
    )

    assert app.participants[-1][BIRTHYEAR_KEY] == 2014
    assert infos == [("Saved", "Added participant: Ada Lovelace")]


def test_save_new_participant_success(monkeypatch):
    infos = []
    monkeypatch.setattr("gui.messagebox.showinfo", lambda title, msg: infos.append((title, msg)))

    class Popup:
        def __init__(self):
            self.destroy_called = False

        def destroy(self):
            self.destroy_called = True

    app = type("Dummy", (), {})()
    app.participants = [{"ID": "2"}, {"ID": 5}]
    app.add_participant_popup = None
    app.add_participant_fields = {}
    calls = {"save_data": 0, "update_list": 0}
    app.save_data = lambda: calls.__setitem__("save_data", calls["save_data"] + 1)
    app.update_list = lambda _data: calls.__setitem__("update_list", calls["update_list"] + 1)
    popup = Popup()

    WeighingApp.save_new_participant(
        app,
        popup,
        DummyField("Ada"),
        DummyField("Lovelace"),
        DummyField("TOP"),
        DummyField("2010"),
        DummyField("weiblich"),
    )

    assert len(app.participants) == 3
    new_p = app.participants[-1]
    assert new_p["ID"] == 6
    assert new_p["Name"] == "Ada Lovelace"
    assert new_p[BIRTHYEAR_KEY] == 2010
    assert new_p[WEIGHT_KEY] == 0.0
    assert new_p[VALID_KEY] is False
    assert new_p[PAID_KEY] is False
    assert popup.destroy_called is True
    assert calls["save_data"] == 1
    assert calls["update_list"] == 1
    assert infos == [("Saved", "Added participant: Ada Lovelace")]


def test_stop_websocket_server_without_loop_returns():
    app = type("Dummy", (), {})()
    app.ws_loop = None
    WeighingApp.stop_websocket_server(app)


def test_stop_websocket_server_closes_clients_and_server(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    class DummyServer:
        def __init__(self):
            self.close_called = False
            self.wait_closed_called = False

        def close(self):
            self.close_called = True

        async def wait_closed(self):
            self.wait_closed_called = True

    class DummyFuture:
        def result(self, timeout=None):
            return None

    class DummyLoop:
        def __init__(self):
            self.called = []
            self.stopped = False

        def stop(self):
            self.stopped = True

        def call_soon_threadsafe(self, fn):
            self.called.append(fn)
            fn()

    def fake_run_coroutine_threadsafe(coro, _loop):
        asyncio.run(coro)
        return DummyFuture()

    monkeypatch.setattr("gui.asyncio.run_coroutine_threadsafe", fake_run_coroutine_threadsafe)

    app = type("Dummy", (), {})()
    app.ws_loop = DummyLoop()
    c1 = DummyClient()
    c2 = DummyClient()
    app.ws_clients = {c1, c2}
    app.ws_server = DummyServer()

    WeighingApp.stop_websocket_server(app)

    assert c1.closed is True
    assert c2.closed is True
    assert app.ws_clients == set()
    assert app.ws_server.close_called is True
    assert app.ws_server.wait_closed_called is True
    assert app.ws_loop.stopped is True


class FakeWebSocket:
    def __init__(self, incoming):
        self._incoming = iter(incoming)
        self.sent = []

    async def send(self, message):
        self.sent.append(json.loads(message))

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._incoming)
        except StopIteration:
            raise StopAsyncIteration


class DummyApp:
    filter_qr = WeighingApp.filter_qr

    def __init__(self):
        self.ws_clients = set()
        self.received_weight = None
        self.received_name = None

    def after(self, _delay_ms, callback):
        callback()

    def apply_received_weight(self, weight):
        self.received_weight = weight

    def apply_qr_search(self, name):
        self.received_name = name

    def handle_incoming_qr(self, qr_data):
        self.apply_qr_search(qr_data.get("name", ""))


def test_ws_handler_accepts_weight_and_qr():
    app = DummyApp()
    ws = FakeWebSocket(
        [
            '{"type":"weight","weight":"7564"}',
            '{"type":"weight","weight":"abc"}',
            "not-json",
            '{"type":"qr","info":{"first_name":"Ada","last_name":"Lovelace"}}',
        ]
    )

    asyncio.run(WeighingApp._ws_handler(app, ws))

    assert app.received_weight == 7564
    assert app.received_name == "Ada Lovelace"

    sent_types = [msg["type"] for msg in ws.sent]
    assert sent_types[0] == "SERVER_READY"
    assert any(msg.get("message") == "weight accepted" for msg in ws.sent)
    assert any(msg.get("message") == "field 'weight' must be int" for msg in ws.sent)
    assert any(msg.get("message") == "invalid json" for msg in ws.sent)
    assert any(msg.get("message") == "qr accepted" for msg in ws.sent)
