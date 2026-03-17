# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

import tkinter as tk
from tkinter import messagebox, filedialog
import pandas as pd
import json
import os
import asyncio
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any
import websockets
try:
    import keyboard
except Exception:
    keyboard = None


PAID = "Zahlung erfolgt"
UNPAID = "Zahlung offen"
WS_HOST = "localhost"
WS_PORT = 8765
WEIGHT_KEY = "Weight"
VALID_KEY = "Valid"
PAID_KEY = "Paid"
BIRTHYEAR_KEY = "Birthyear"
TEXT_KEYS = ["Firstname", "Lastname", "Name", "Club", "Gender"]
FIELD_WIDTH = 20
LABEL_WIDTH = 22
DEFAULT_MIN_AGE_YEARS = 6
DEFAULT_MAX_AGE_YEARS = 120

THEME = {
    "bg": "#1e1e1e",        # VSCode Dark+ Background
    "fg": "#f0f0f2",        # text
    "accent": "#22AAF0",    # PO Palette: Fresh Sky
    "secondary": "#252526", # VSCode Dark+ Sidebar/Secondary
    "input_bg": "#3c3c3c",  # VSCode Dark+ Input Field
    "input_fg": "#f0f0f2",  # text
    "success": "#4CCD70",   # PO Palette: Emerald
    "error": "#B7413F",     # Option 3: Earthy Brick Red
    "männlich" : "#22AAF0", # PO Palette: Fresh Sky
    "weiblich" : "#E590E8"  # PO Palette: Violet
}



class WeighingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Judo Weighing Station")
        width = self.winfo_screenwidth()
        height = self.winfo_screenheight()
        self.geometry(f"{width}x{height-50}+0+0")
        self.configure(bg=THEME["bg"])
        
        self.participants: List[Dict[str, Any]] = []
        self.visible_participants: List[Dict[str, Any]] = []
        self.selected_participant: Optional[Dict[str, Any]] = None
        self.data_file_path: str = ""
        self.pending_received_weight: Optional[int] = None
        self.weight_decimal_places: int = 0
        self.weight_popup: Optional[tk.Toplevel] = None
        self.weight_popup_name_label: Optional[tk.Label] = None
        self.weight_popup_value_label: Optional[tk.Label] = None
        self.add_participant_popup: Optional[tk.Toplevel] = None
        self.settings_popup: Optional[tk.Toplevel] = None
        self.add_participant_fields: Dict[str, Any] = {}
        self.saved_form_snapshot: Optional[Dict[str, str]] = None
        self.duplicate_warning_after_id: Optional[str] = None
        self.min_age_years: int = DEFAULT_MIN_AGE_YEARS
        self.max_age_years: int = DEFAULT_MAX_AGE_YEARS
        self.double_start_mode: str = "standard"
        self.double_start_years: List[int] = []
        self.age_class_tolerance: Dict[str, Dict[str, float]] = {
            "mixed": {"U9": 0.0, "U11": 0.0},
            "male": {"U13": 0.0, "U15": 0.0, "U18": 0.0, "Aktive": 0.0},
            "female": {"U13": 0.0, "U15": 0.0, "U18": 0.0, "Aktive": 0.0},
        }

        self.ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.ws_server = None
        self.ws_clients = set()
        self.qr_ws_clients = set()
        self.weight_ws_clients = set()
        self.scanner_ws_clients = set()
        self.external_program_threads: List[threading.Thread] = []
        self.external_programs_started = False
         
        self.create_layout()
        self.load_settings()
        self.load_data()
        self.start_websocket_server()
        self.prompt_for_data_source_selection()
        self.register_keyboard_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def create_action_buttons(self):
        """Creates the bottom navigation and action buttons."""
        if not hasattr(self, 'main_container'):
            parent = self
            pack_side = tk.BOTTOM
        else:
            parent = self.main_container
            pack_side = tk.BOTTOM
             
        btn_container = tk.Frame(parent, bg=THEME["bg"])
        btn_container.pack(side=pack_side, fill=tk.X, pady=(20, 30))

        btn_opts = {
            "bg": THEME["input_bg"], "fg": "#f0f0f2", 
            "font": ("Rubik", 10, "bold"), "bd": 1, 
            "relief": "flat", "height": 2, "cursor": "hand2"
        }
        
        self.btn_save = tk.Button(btn_container, text="Speichern", command=self.save, width=18, **btn_opts)
        self.btn_save.pack(side=tk.LEFT, padx=5)

        tk.Button(btn_container, text="Gewicht nehmen", command=self.read_scale, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        tk.Button(btn_container, text="Einstellungen", command=self.open_settings_window, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)
        double_start_btn_opts = dict(btn_opts)
        double_start_btn_opts.update(
            {
                "bg": "#FFD54A",
                "fg": "black",
                "activebackground": "#FFD54A",
                "activeforeground": "black",
            }
        )
        self.btn_double_start = tk.Button(
            btn_container,
            text="Doppelstart",
            command=self.open_double_start_window,
            width=18,
            **double_start_btn_opts,
        )
        self.btn_double_start.pack(side=tk.LEFT, padx=5)

        add_btn_opts = dict(btn_opts)
        add_btn_opts.update(
            {
                "bg": "#f0f0f2",
                "fg": "black",
                "activebackground": "#f0f0f2",
                "activeforeground": "black",
            }
        )

        self.btn_add = tk.Button(
            btn_container,
            text="Neuer Teilnehmer",
            command=self.open_add_participant_window,
            width=18,
            **add_btn_opts,
        )
        self.btn_add.pack(side=tk.RIGHT, padx=5)

        delete_btn_opts = dict(btn_opts)
        delete_btn_opts.update(
            {
                "bg": THEME["error"],
                "fg": "#f0f0f2",
                "activebackground": THEME["error"],
                "activeforeground": "#f0f0f2",
            }
        )
        self.btn_delete = tk.Button(
            btn_container,
            text="Teilnehmer löschen",
            command=getattr(self, "delete_selected_participant", lambda: None),
            width=18,
            **delete_btn_opts,
        )
        self.btn_delete.pack(side=tk.RIGHT, padx=5)

        self.duplicate_warning_frame = tk.Frame(
            self.main_container,
            bg=THEME["error"],
            bd=0,
            highlightthickness=0,
        )
        self.duplicate_warning_label = tk.Label(
            self.duplicate_warning_frame,
            text="Achtung: Mehrere Personen gefunden",
            bg=THEME["error"],
            fg="#f0f0f2",
            font=("Rubik", 14, "bold"),
            padx=20,
            pady=10,
        )
        
        self.duplicate_warning_label.pack(side=tk.LEFT)
    
        self.duplicate_warning_close_button = tk.Button(
            self.duplicate_warning_frame,
            text="x",
            command=self.hide_duplicate_warning,
            bg=THEME["error"],
            fg="#f0f0f2",
            activebackground=THEME["error"],
            activeforeground="#f0f0f2",
            bd=0,
            relief="flat",
            font=("Rubik", 9, "bold"),
            padx=8,
            pady=4,
            cursor="hand2",
        )
        self.duplicate_warning_close_button.pack(side=tk.LEFT, padx=(0, 4))
        self.duplicate_warning_frame.place_forget()


    def create_label(self, parent, text, r, c, pady=(28, 0)):
        """Creates a standard label at the specified grid position."""
        lbl = tk.Label(
            parent,
            text=text,
            bg=THEME["bg"],
            fg=THEME["fg"],
            font=("Rubik", 12, "bold"),
            anchor="w",
            width=LABEL_WIDTH,
        )
        lbl.grid(row=r, column=c, padx=14, pady=pady, sticky="n")

    def create_entry_value(self, parent, r, c):
        """Creates an editable entry field at the specified grid position."""
        entry = tk.Entry(parent, bg=THEME["input_bg"], fg="#f0f0f2", font=("Rubik", 14), justify="left", width=FIELD_WIDTH)
        entry.grid(row=r, column=c, padx=14, pady=(5, 14), ipady=4, sticky="n")
        return entry

    def create_status_dropdown(self, parent, variable, options, r, c):
        """Creates a status dropdown widget."""
        dropdown = tk.OptionMenu(parent, variable, *options)
        dropdown.config(
            bg=THEME["input_bg"],
            fg="black",
            activebackground=THEME["input_bg"],
            activeforeground="black",
            highlightthickness=0,
            bd=0,
            font=("Rubik", 12, "bold"),
            width=max(FIELD_WIDTH - 1, 1),
            anchor="w",
        )
        dropdown["menu"].config(
            bg=THEME["input_bg"],
            fg=THEME["fg"],
            activebackground=THEME["accent"],
            activeforeground="black",
            font=("Rubik", 11),
        )
        dropdown.grid(row=r, column=c, padx=14, pady=(5, 14), sticky="n")
        return dropdown

    @staticmethod
    def to_bool(value: Any) -> bool:
        """Converts mixed json/string/boolean values to bool."""
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in ["true", "1", "yes", "ja"]

    @staticmethod
    def normalize_ui_gender(value: Any) -> str:
        """Maps stored gender values to UI values (männlich/weiblich)."""
        v = str(value or "").strip().lower()
        if v in {"m", "male", "mann", "männlich"}:
            return "männlich"
        if v in {"w", "f", "female", "frau", "weiblich"}:
            return "weiblich"
        return "männlich"

    @staticmethod
    def normalize_json_gender(value: Any) -> str:
        """Maps UI or legacy gender values to storage values (m/w)."""
        return "m" if WeighingApp.normalize_ui_gender(value) == "männlich" else "w"

    def update_status_dropdown_colors(self, *args):
        """Updates dropdown backgrounds to reflect status selection."""
        valid_color = THEME["success"] if self.valid_var.get() == "gültig" else THEME["error"]
        paid_color = THEME["success"] if self.paid_var.get() == PAID else THEME["error"]
        gender_color = THEME["männlich"] if self.gender_var.get() == "männlich" else THEME["weiblich"]

        self.val_valid.config(bg=valid_color)
        self.val_paid.config(bg=paid_color)
        self.val_gender.config(bg=gender_color)
        self.update_save_button_state()

    @staticmethod
    def parse_weight(value: Any) -> Optional[float]:
        """Parses and validates weight input."""
        txt = str(value or "").strip()
        if not txt:
            return None
        txt = txt.replace(",", ".")
        try:
            parsed = float(txt)
        except ValueError:
            return None
        if parsed < 0:
            return None
        return parsed

    def get_form_snapshot(self) -> Dict[str, str]:
        """Returns current editable form state for dirty-checking."""
        mode_value = ""
        birth_year_txt = self.val_birthyear.get().strip() if hasattr(self, "val_birthyear") else ""
        if birth_year_txt.isdigit() and self.is_birth_year_double_start_eligible(int(birth_year_txt)):
            mode_value = self.get_saved_double_start_mode()
        return {
            "Firstname": self.val_prename.get().strip(),
            "Lastname": self.val_surname.get().strip(),
            "Club": self.val_club.get().strip(),
            "Birthyear": self.val_birthyear.get().strip(),
            "Weight": self.weight_var.get().strip(),
            "Gender": self.gender_var.get().strip(),
            "Valid": self.valid_var.get().strip(),
            "Paid": self.paid_var.get().strip(),
            "Mode": mode_value,
        }

    def is_form_invalid(self) -> bool:
        """Checks if one or more required inputs are empty or invalid."""
        required_values = [
            self.val_prename.get().strip(),
            self.val_surname.get().strip(),
            self.val_club.get().strip(),
            self.val_birthyear.get().strip(),
            self.weight_var.get().strip(),
        ]
        if any(not value for value in required_values):
            return True

        min_age = getattr(self, "min_age_years", DEFAULT_MIN_AGE_YEARS)
        max_age = getattr(self, "max_age_years", DEFAULT_MAX_AGE_YEARS)
        if WeighingApp.parse_birth_year(self.val_birthyear.get().strip(), min_age, max_age) is None:
            return True
        if WeighingApp.parse_weight(self.weight_var.get()) is None:
            return True
        return False

    def set_save_button_default_style(self):
        """Restores save button style to existing default look."""
        if hasattr(self, "btn_save"):
            self.btn_save.config(
                bg=THEME["input_bg"],
                fg="#f0f0f2",
                activebackground=THEME["input_bg"],
                activeforeground="#f0f0f2",
            )

    def update_save_button_state(self, _event=None):
        """Updates box border and save button color based on validity and dirty state."""
        if not hasattr(self, "btn_save"):
            return
        if not self.selected_participant:
            if hasattr(self, "details_box_frame"):
                self.details_box_frame.config(
                    highlightbackground="#f0f0f2",
                    highlightcolor="#f0f0f2",
                )
            self.set_save_button_default_style()
            if hasattr(self, "save_state_hint_label"):
                self.save_state_hint_label.config(text="")
            return

        is_invalid = self.is_form_invalid()
        is_dirty = self.saved_form_snapshot is not None and self.get_form_snapshot() != self.saved_form_snapshot

        if is_invalid:
            if hasattr(self, "details_box_frame"):
                self.details_box_frame.config(
                    highlightbackground=THEME["error"],
                    highlightcolor=THEME["error"],
                )
            self.btn_save.config(
                bg=THEME["error"],
                fg="#f0f0f2",
                activebackground=THEME["error"],
                activeforeground="#f0f0f2",
            )
            if hasattr(self, "save_state_hint_label"):
                self.save_state_hint_label.config(
                    text="Ein oder mehrere Einträge sind leer oder falsch",
                    fg=THEME["error"],
                )
            return

        if is_dirty:
            if hasattr(self, "details_box_frame"):
                self.details_box_frame.config(
                    highlightbackground="#FFD54A",
                    highlightcolor="#FFD54A",
                )
            self.btn_save.config(
                bg="#FFD54A",
                fg="black",
                activebackground="#FFD54A",
                activeforeground="black",
            )
            if hasattr(self, "save_state_hint_label"):
                self.save_state_hint_label.config(
                    text="Bitte speichern Sie die Änderungen",
                    fg="#FFD54A",
                )
            return

        if hasattr(self, "details_box_frame"):
            self.details_box_frame.config(
                highlightbackground="#f0f0f2",
                highlightcolor="#f0f0f2",
            )
        self.set_save_button_default_style()
        if hasattr(self, "save_state_hint_label"):
            self.save_state_hint_label.config(text="")

    @staticmethod
    def get_birth_year_text(p: Dict[str, Any]) -> str:
        """Returns a displayable birth year string."""
        raw_year = p.get(BIRTHYEAR_KEY, p.get("BirthYear"))
        if raw_year is None:
            return "---"
        txt = str(raw_year).strip()
        if txt:
            return txt
        return "---"

    @staticmethod
    def parse_birth_year(
        value: Any,
        min_age_years: int = DEFAULT_MIN_AGE_YEARS,
        max_age_years: int = DEFAULT_MAX_AGE_YEARS,
    ) -> Optional[int]:
        """Parses and validates a year value."""
        txt = str(value or "").strip()
        if not txt.isdigit():
            return None
        year = int(txt)
        now_year = datetime.now().year
        min_year = now_year - max_age_years
        max_year = now_year - min_age_years
        if min_year <= year <= max_year:
            return year
        return None

    def filter_qr(self, info: Any) -> Dict[str, Any]:
        """Normalizes QR info and combines first/last name to one display field."""
        if not isinstance(info, dict):
            return {
                "name": "",
                "first_name": "",
                "last_name": "",
                "birth_year": 0,
                "exp_timestamp": None,
            }

        first_name = str(info.get("first_name") or info.get("first") or "").strip()
        last_name = str(info.get("last_name") or info.get("last") or "").strip()
        full_name = f"{first_name} {last_name}".strip()

        return {
            "name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "birth_year": info.get("birth_year"),
            "exp_timestamp": info.get("exp_timestamp"),
        }

    def fill_add_participant_from_qr(self, qr_data: Dict[str, Any]):
        """Autofills add-participant dialog fields if the popup is currently open."""
        popup = self.add_participant_popup
        if not popup or not popup.winfo_exists():
            return

        e_first = self.add_participant_fields.get("e_first")
        e_last = self.add_participant_fields.get("e_last")
        e_birthyear = self.add_participant_fields.get("e_birthyear")
        valid_var = self.add_participant_fields.get("valid_var")
        if not e_first or not e_last:
            return

        first_name = str(qr_data.get("first_name") or "").strip()
        last_name = str(qr_data.get("last_name") or "").strip()
        birth_year = qr_data.get("birth_year")

        if first_name:
            e_first.delete(0, tk.END)
            e_first.insert(0, first_name)
        if last_name:
            e_last.delete(0, tk.END)
            e_last.insert(0, last_name)
        if birth_year:
            e_birthyear.delete(0, tk.END)
            e_birthyear.insert(0, birth_year)
        if valid_var is not None:
            valid_var.set("gültig" if self._qr_is_valid(qr_data.get("exp_timestamp")) else "ungültig")
        popup.lift()
        e_first.focus_set()

    def handle_incoming_qr(self, qr_data: Dict[str, Any]):
        """Applies default QR behavior for search and add-participant autofill."""
        popup = self.add_participant_popup
        if popup and popup.winfo_exists():
            self.fill_add_participant_from_qr(qr_data)
            return
        self.apply_qr_match(qr_data)
        
    
    def get_filtered_participants(self, query: str) -> List[Dict[str, Any]]:
        """Returns participants matching search query."""
        return self.search_participants(query)


    @staticmethod
    def _normalize_birth_year(value: Any) -> Optional[int]:
        txt = str(value or "").strip()
        if txt.isdigit():
            return int(txt)
        return None

    @staticmethod
    def _qr_is_valid(exp_timestamp: Any) -> bool:
        try:
            exp = int(exp_timestamp)
        except Exception:
            return False
        return datetime.now().timestamp() <= exp

    def apply_qr_match(self, qr_data: Dict[str, Any]):
        """Matches QR data by exact full identity first, then falls back to search filter."""
        qr_first = str(qr_data.get("first_name") or "").strip().lower()
        qr_last = str(qr_data.get("last_name") or "").strip().lower()
        qr_name = str(qr_data.get("name") or "").strip()
        qr_birth_year = self._normalize_birth_year(qr_data.get("birth_year"))

        exact_matches = []
        for p in self.participants:
            first = str(p.get("Firstname") or "").strip().lower()
            last = str(p.get("Lastname") or "").strip().lower()
            birth_year = self._normalize_birth_year(p.get(BIRTHYEAR_KEY, p.get("BirthYear")))
            if first == qr_first and last == qr_last and birth_year == qr_birth_year:
                exact_matches.append(p)

        if exact_matches:
            qr_is_valid = self._qr_is_valid(qr_data.get("exp_timestamp"))
            exact_matches[0][VALID_KEY] = qr_is_valid
            self.update_list(exact_matches)
            if len(exact_matches) > 1:
                self.show_duplicate_warning()
            else:
                self.hide_duplicate_warning()

            self.selected_participant = exact_matches[0]
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(0)
            self.listbox.activate(0)
            self.listbox.see(0)
            self.show_details(exact_matches[0])
            return

        filtered = self.get_filtered_participants(qr_name)
        self.update_list(filtered)
        self.listbox.selection_clear(0, tk.END)
        self.clear_participant_details()
        if len(filtered) > 1:
            self.show_duplicate_warning()
        else:
            self.hide_duplicate_warning()
        qr_status = "gültig" if self._qr_is_valid(qr_data.get("exp_timestamp")) else "abgelaufen"
        self.show_qr_mismatch_warning(qr_status)

    def show_qr_mismatch_warning(self, qr_status: str):
        """Shows styled warning popup for QR mismatches."""
        popup = tk.Toplevel(self)
        popup.title("Kein 100%-Treffer")
        popup.configure(bg=THEME["bg"])
        popup.resizable(False, False)
        popup.transient(self)
        popup.grab_set()

        popup_w = 520
        popup_h = 260
        if hasattr(popup, "update_idletasks"):
            popup.update_idletasks()
        try:
            self.update_idletasks()
            root_x = self.winfo_rootx()
            root_y = self.winfo_rooty()
            root_w = self.winfo_width()
            root_h = self.winfo_height()
            x = root_x + (root_w - popup_w) // 2
            y = root_y + (root_h - popup_h) // 2
        except Exception:
            screen_w = popup.winfo_screenwidth()
            screen_h = popup.winfo_screenheight()
            x = (screen_w - popup_w) // 2
            y = (screen_h - popup_h) // 2
        popup.geometry(f"{popup_w}x{popup_h}+{max(x, 0)}+{max(y, 0)}")

        is_valid = str(qr_status).strip().lower() == "gültig"
        status_color = THEME["success"] if is_valid else THEME["error"]

        tk.Label(
            popup,
            text="keinen vollständig übereinstimmenden Daten gefunden.",
            bg=THEME["bg"],
            fg=THEME["fg"],
            font=("Rubik", 12, "bold"),
            wraplength=470,
            justify="center",
        ).pack(pady=(24, 10), padx=20)

        status_frame = tk.Frame(popup, bg=THEME["bg"])
        status_frame.pack(pady=(0, 12))
        tk.Label(
            status_frame,
            text="QR Code ist ",
            bg=THEME["bg"],
            fg=THEME["fg"],
            font=("Rubik", 14),
        ).pack(side=tk.LEFT)
        tk.Label(
            status_frame,
            text=qr_status,
            bg=THEME["bg"],
            fg=status_color,
            font=("Rubik", 20, "bold"),
        ).pack(side=tk.LEFT)

        tk.Label(
            popup,
            text="Bitte manuel ändern.",
            bg=THEME["bg"],
            fg=THEME["fg"],
            font=("Rubik", 11),
        ).pack(pady=(0, 18))

        tk.Button(
            popup,
            text="OK",
            command=popup.destroy,
            bg=THEME["input_bg"],
            fg="#f0f0f2",
            activebackground=THEME["input_bg"],
            activeforeground="#f0f0f2",
            font=("Rubik", 10, "bold"),
            width=12,
        ).pack()

    def search_participants(self, query: str) -> list[dict]:
        q = (query or "").lower().strip()
        if not q:
            return self.participants
        q_tokens = q.split()

        from difflib import SequenceMatcher
        results = []

        def token_match(text: str) -> bool:
            return all(token in text for token in q_tokens)

        def token_similarity(q_parts: list[str], text: str) -> float:
            text_tokens = text.split()
            if not q_parts or not text_tokens:
                return 0.0
            sims = []
            for q_part in q_parts:
                best = max(SequenceMatcher(None, q_part, t).ratio() for t in text_tokens)
                sims.append(best)
            return sum(sims) / len(sims)

        for p in self.participants:
            name = str(p.get("Name", "")).lower()
            club = str(p.get("Club", p.get("Verein", ""))).lower()
            score = 0
            matched = False

            if token_match(name):
                matched = True
                score = 100

                if name.startswith(q):
                    score += 20

            elif token_match(club):
                matched = True
                score = 60

            if not matched:
                name_similarity = token_similarity(q_tokens, name)
                club_similarity = token_similarity(q_tokens, club)
                similarity = max(name_similarity, club_similarity)

                if similarity >= 0.85:
                    matched = True
                    score = int(similarity * 100)

            if matched:
                results.append((score, p))

        results.sort(key=lambda x: x[0], reverse=True)

        return [p for _, p in results]
    
    def show_duplicate_warning(self):
        if self.duplicate_warning_after_id is not None:
            self.after_cancel(self.duplicate_warning_after_id)
            self.duplicate_warning_after_id = None
        self.duplicate_warning_frame.place(relx=0.5, rely=0.5, anchor="center")
        self.duplicate_warning_frame.lift()
        self.duplicate_warning_after_id = self.after(5000, self.hide_duplicate_warning)
        
    def hide_duplicate_warning(self):
        if self.duplicate_warning_after_id is not None:
            self.after_cancel(self.duplicate_warning_after_id)
            self.duplicate_warning_after_id = None
        self.duplicate_warning_frame.place_forget()

    def clear_participant_details(self):
        """Clears participant detail inputs in the main view."""
        self.selected_participant = None
        self.saved_form_snapshot = None
        self.val_prename.delete(0, tk.END)
        self.val_surname.delete(0, tk.END)
        self.val_birthyear.delete(0, tk.END)
        self.val_club.delete(0, tk.END)
        self.weight_var.delete(0, tk.END)
        self.valid_var.set("ungültig")
        self.paid_var.set(UNPAID)
        self.gender_var.set("weiblich")
        self.update_status_dropdown_colors()
        if hasattr(self, "update_tolerance_label"):
            WeighingApp.update_tolerance_label(self)
        if hasattr(self, "update_double_start_visibility"):
            WeighingApp.update_double_start_visibility(self)
        self.update_save_button_state()
    
    def filter_list(self, *args):
        """Filters the participant list based on the search bar input."""
        query = self.search_var.get()
        if query.strip():
            self.clear_participant_details()
        filtered = self.get_filtered_participants(query)
        self.update_list(filtered)

    def update_list(self, data: List[Dict]):
        """Refreshes the sidebar listbox with the provided data."""
        self.visible_participants = list(data)
        self.listbox.delete(0, tk.END)
        if not self.visible_participants:
            self.listbox.insert(tk.END, "kein Teilnehmer gefunden")
            return
        for p in self.visible_participants:
            name = p.get('Name', 'Unknown')
            self.listbox.insert(tk.END, f"  {name}")

    def on_select(self, event):
        """Handles selection of a participant from the listbox."""
        selection = self.listbox.curselection()
        if not selection:
            return
        
        index = selection[0]
        if index < 0 or index >= len(self.visible_participants):
            return

        selected = self.visible_participants[index]
        self.selected_participant = selected
        self.show_details(selected)

    def load_data(self):
        """Loads participant data from the Excel file."""
        if not self.data_file_path:
            self.participants = []
            self.update_list(self.participants)
            return

        if not os.path.exists(self.data_file_path):
             messagebox.showerror("Error", f"Data file not found: {self.data_file_path}")
             return

        if hasattr(self, "load_event_settings"):
            self.load_event_settings()
        try:
            with open(self.data_file_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            raw_participants = data if isinstance(data, list) else data.get("participants", [])
            self.participants = [p for p in raw_participants if isinstance(p, dict)]
            self.update_list(self.participants)
        except Exception as e:
            messagebox.showerror("Error", f"Could not load data: {e}")         

    def load_settings(self):
        """Applies startup defaults without loading persisted file settings."""
        self.weight_decimal_places = 0
        self.data_file_path = ""
        self.min_age_years = DEFAULT_MIN_AGE_YEARS
        self.max_age_years = DEFAULT_MAX_AGE_YEARS
        self.double_start_mode = "standard"
        self.double_start_years = []

    def load_event_settings(self):
        """Loads age range and tolerance config from setting.json near selected data source."""
        self.min_age_years = DEFAULT_MIN_AGE_YEARS
        self.max_age_years = DEFAULT_MAX_AGE_YEARS
        self.double_start_years = []
        self.age_class_tolerance = {
            "mixed": {"U9": 0.0, "U11": 0.0},
            "male": {"U13": 0.0, "U15": 0.0, "U18": 0.0, "Aktive": 0.0},
            "female": {"U13": 0.0, "U15": 0.0, "U18": 0.0, "Aktive": 0.0},
        }

        if not self.data_file_path:
            return

        settings_path = os.path.join(os.path.dirname(self.data_file_path), "setting.json")
        if not os.path.exists(settings_path):
            return

        try:
            with open(settings_path, "r", encoding="utf-8-sig") as f:
                cfg = json.load(f)
        except Exception:
            return

        age_range = cfg.get("ageRange", {}) if isinstance(cfg, dict) else {}
        min_age_raw = age_range.get("minAge")
        max_age_raw = age_range.get("maxAge")
        if isinstance(min_age_raw, int) and min_age_raw >= 0:
            self.min_age_years = min_age_raw
        if isinstance(max_age_raw, int) and max_age_raw >= self.min_age_years:
            self.max_age_years = max_age_raw

        tol_cfg = cfg.get("ageClassTolerance", {}) if isinstance(cfg, dict) else {}
        if isinstance(tol_cfg, dict):
            for g in ["mixed", "male", "female"]:
                raw_map = tol_cfg.get(g)
                if not isinstance(raw_map, dict):
                    continue
                for klass, value in raw_map.items():
                    if not isinstance(klass, str):
                        continue
                    if isinstance(value, (int, float)):
                        klass_name = klass.strip()
                        self.age_class_tolerance[g][klass_name] = float(value)

        raw_years = cfg.get("doubleStartYears", []) if isinstance(cfg, dict) else []
        if isinstance(raw_years, list):
            parsed_years = []
            for year in raw_years:
                try:
                    y = int(year)
                except Exception:
                    continue
                parsed_years.append(y)
            self.double_start_years = parsed_years

        if hasattr(self, "update_tolerance_label"):
            WeighingApp.update_tolerance_label(self)
        if hasattr(self, "update_double_start_label"):
            WeighingApp.update_double_start_label(self)
        if hasattr(self, "update_double_start_visibility"):
            WeighingApp.update_double_start_visibility(self)

    def update_double_start_label(self):
        """Updates the yellow status label above the QR scan hint."""
        if not hasattr(self, "double_start_status_label"):
            return
        self.double_start_status_label.config(
            text=f"Doppelstart: {self.double_start_mode}"
        )

    def is_double_start_eligible(self) -> bool:
        """Returns True when current birth year is allowed for double start."""
        if not hasattr(self, "val_birthyear"):
            return False
        txt = self.val_birthyear.get().strip()
        if not txt.isdigit():
            return False
        return int(txt) in set(self.double_start_years or [])

    def is_birth_year_double_start_eligible(self, birth_year: int) -> bool:
        """Returns True when the given birth year is configured for double start."""
        return int(birth_year) in set(self.double_start_years or [])

    def get_saved_double_start_mode(self) -> str:
        """Returns persisted mode value (standard, höher, doppel)."""
        mode = str(self.double_start_mode or "").strip().lower()
        if mode == "höher":
            return "höher"
        if mode == "doppel":
            return "doppel"
        return "standard"

    def update_double_start_visibility(self, *_args):
        """Shows/hides double-start button and status label for allowed birth years."""
        eligible = self.is_double_start_eligible()

        if hasattr(self, "btn_double_start"):
            if eligible:
                if not self.btn_double_start.winfo_manager():
                    self.btn_double_start.pack(side=tk.LEFT, padx=5)
            elif self.btn_double_start.winfo_manager():
                self.btn_double_start.pack_forget()

        if hasattr(self, "double_start_status_label"):
            if eligible:
                self.double_start_status_label.grid()
                self.update_double_start_label()
            else:
                self.double_start_status_label.grid_remove()

    def open_double_start_window(self):
        """Opens a small dialog to choose the double-start mode."""
        popup = tk.Toplevel(self)
        popup.title("Doppelstart")
        popup.geometry("320x210")
        popup.configure(bg=THEME["bg"])
        popup.resizable(False, False)
        popup.transient(self)
        popup.update_idletasks()
        try:
            self.update_idletasks()
            x_pos = self.winfo_rootx() + (self.winfo_width() - 320) // 2
            y_pos = self.winfo_rooty() + (self.winfo_height() - 210) // 2
            popup.geometry(f"320x210+{max(x_pos, 0)}+{max(y_pos, 0)}")
        except Exception:
            pass
        popup.grab_set()

        tk.Label(
            popup,
            text="Doppelstart-Modus",
            bg=THEME["bg"],
            fg=THEME["fg"],
            font=("Rubik", 12, "bold"),
        ).pack(pady=(14, 8))

        mode_var = tk.StringVar(value=self.double_start_mode)
        for value, text in [
            ("standard", "standard"),
            ("höher", "höher"),
            ("doppel", "doppel"),
        ]:
            tk.Radiobutton(
                popup,
                text=text,
                variable=mode_var,
                value=value,
                bg=THEME["bg"],
                fg=THEME["fg"],
                activebackground=THEME["bg"],
                activeforeground=THEME["fg"],
                selectcolor=THEME["input_bg"],
                font=("Rubik", 11),
                anchor="w",
                width=14,
            ).pack(pady=2)

        btn_frame = tk.Frame(popup, bg=THEME["bg"])
        btn_frame.pack(pady=(14, 8))

        def apply_mode():
            self.double_start_mode = mode_var.get()
            self.update_double_start_label()
            self.update_save_button_state()
            popup.destroy()

        tk.Button(
            btn_frame,
            text="Übernehmen",
            command=apply_mode,
            bg=THEME["success"],
            fg="black",
            font=("Rubik", 10, "bold"),
            width=12,
        ).pack(side=tk.LEFT, padx=6)

        tk.Button(
            btn_frame,
            text="Cancel",
            command=popup.destroy,
            bg=THEME["error"],
            fg="#f0f0f2",
            font=("Rubik", 10, "bold"),
            width=12,
        ).pack(side=tk.LEFT, padx=6)

    @staticmethod
    def get_age_class(age_years: int) -> str:
        """Maps age in years to configured age classes."""
        if age_years <= 8:
            return "U9"
        if age_years <= 10:
            return "U11"
        if age_years <= 12:
            return "U13"
        if age_years <= 14:
            return "U15"
        if age_years <= 17:
            return "U18"
        return "Aktive"

    def get_tolerance_for(self, gender_ui: str, age_class: str) -> Optional[float]:
        """Resolves tolerance by age class and gender with mixed fallback."""
        cfg_key = "male" if gender_ui == "männlich" else "female"
        val = self.age_class_tolerance.get(cfg_key, {}).get(age_class)
        if val is None and age_class == "Aktive":
            val = self.age_class_tolerance.get(cfg_key, {}).get("Aktive")
        if val is None:
            val = self.age_class_tolerance.get("mixed", {}).get(age_class)
        if val is None and age_class == "Aktive":
            val = self.age_class_tolerance.get("mixed", {}).get("Aktive")
        return val

    def update_tolerance_label(self, *_args):
        """Updates tolerance hint below weight input based on current gender and birth year."""
        if not hasattr(self, "tolerance_hint_prefix_label") or not hasattr(self, "tolerance_hint_value_label"):
            return

        birth_year = WeighingApp.parse_birth_year(self.val_birthyear.get().strip())
        if birth_year is None:
            self.tolerance_hint_prefix_label.config(text="")
            self.tolerance_hint_value_label.config(text="")
            return

        age_years = datetime.now().year - birth_year
        age_class = self.get_age_class(age_years)
        gender_ui = WeighingApp.normalize_ui_gender(self.gender_var.get())
        tolerance = self.get_tolerance_for(gender_ui, age_class)
        if tolerance is None:
            self.tolerance_hint_prefix_label.config(text="")
            self.tolerance_hint_value_label.config(text="")
            return

        self.tolerance_hint_prefix_label.config(text=f"Toleranz ({age_class}):")
        self.tolerance_hint_value_label.config(text=f"{tolerance:g} g")

    def prompt_for_data_source_selection(self):
        """Prompts user to choose a data source when app starts without one."""
        if self.data_file_path:
            return
        messagebox.showinfo("Achtung", "Bitte Datenquelle auswählen.")
        self.open_settings_window()

    def format_scale_weight(self, raw_weight: int) -> str:
        """Formats integer scale input based on configured decimal places."""
        places = self.weight_decimal_places
        value = raw_weight / (10 ** places)
        return f"{value:.{places}f}"

    def show_details(self, p: Dict):
        """Populates the detail view with the selected participant's data."""
        full_name = str(p.get('Name', 'Unknown'))
        parts = full_name.split()
        if len(parts) > 1:
            prename = parts[0]
            surname = " ".join(parts[1:])
        else:
            prename = full_name
            surname = ""
            
        if 'Firstname' in p and pd.notna(p['Firstname']):
            prename = p['Firstname']
             
        self.val_prename.delete(0, tk.END)
        self.val_prename.insert(0, str(prename))
        
        self.val_surname.delete(0, tk.END)
        self.val_surname.insert(0, str(surname))
        
        self.val_birthyear.delete(0, tk.END)
        self.val_birthyear.insert(0, self.get_birth_year_text(p))

        self.val_club.delete(0, tk.END)
        self.val_club.insert(0, str(p.get("Club")))

        is_valid = self.to_bool(p.get(VALID_KEY, False))
        is_paid = self.to_bool(p.get(PAID_KEY, False))
        
        ui_gender = WeighingApp.normalize_ui_gender(p.get("Gender"))

        self.valid_var.set("gültig" if is_valid else "ungültig")
        self.paid_var.set(PAID if is_paid else UNPAID)
        self.gender_var.set(ui_gender)
        self.update_status_dropdown_colors()

        weight = p.get(WEIGHT_KEY, 0.0)
        self.weight_var.delete(0, tk.END)
        self.weight_var.insert(0, str(weight))
        if hasattr(self, "update_tolerance_label"):
            WeighingApp.update_tolerance_label(self)
        if hasattr(self, "update_double_start_visibility"):
            WeighingApp.update_double_start_visibility(self)
        self.saved_form_snapshot = self.get_form_snapshot()
        self.update_save_button_state()

    def save_data(self):
        """Writes current participant data back to JSON."""
        if not self.data_file_path:
            raise RuntimeError("No data source selected.")
        with open(self.data_file_path, "w", encoding="utf-8") as f:
            json.dump(self.participants, f, ensure_ascii=False, indent=2)

    def read_scale(self):
        """Requests a new reading from the connected weight scanner."""
        if self.pending_received_weight is not None:
            self.show_weight_popup(self.pending_received_weight)
            return

        if not self.ws_loop or not self.ws_clients:
            messagebox.showwarning("Scale", "No scale client connected.")
            return

        self.send_weight_request()

    def trigger_qr_scan_hotkey(self, _event=None):
        """Triggers scanner popup hotkey (F12) from GUI click."""
        try:
            print("Triggering QR scan hotkey (F12)")
            keyboard.press_and_release("F12")
        except Exception as e:
            messagebox.showerror("QR Scan", f"F12 konnte nicht ausgelost werden: {e}")

    def register_keyboard_shortcuts(self):
        """Registers GUI-wide keyboard shortcuts."""
        self.bind_all("<Control-s>", self.handle_save_shortcut)
        self.bind_all("<Control-S>", self.handle_save_shortcut)
        self.bind_all("<Return>", self.handle_delete_shortcut)

    def _is_main_window_event(self, event) -> bool:
        """Returns true when event belongs to the main app window."""
        widget = getattr(event, "widget", None)
        if widget is None:
            return True
        try:
            return widget.winfo_toplevel() is self
        except Exception:
            return False

    def handle_save_shortcut(self, event=None):
        """Handles Ctrl+S like the save button."""
        if event is not None and not self._is_main_window_event(event):
            return
        self.save()
        return "break"

    def handle_delete_shortcut(self, event=None):
        """Handles Enter: sends space and then backspace."""
        if event is not None and not self._is_main_window_event(event):
            return
        if keyboard is not None:
            try:
                keyboard.press_and_release("space")
                keyboard.press_and_release("backspace")
            except Exception:
                pass
        return "break"

    def accept_pending_weight(self):
        """Accepts pending weight, writes it into the field, and saves immediately."""
        if self.pending_received_weight is None:
            return
        formatted_weight = self.format_scale_weight(self.pending_received_weight)
        self.weight_var.delete(0, tk.END)
        self.weight_var.insert(0, formatted_weight)
        self.save()
        self.pending_received_weight = None
        self.close_weight_popup()

    def cancel_pending_weight(self):
        """Rejects the pending weight and closes the confirmation popup."""
        self.pending_received_weight = None
        self.close_weight_popup()

    def save(self):
        """Saves edited person data and weight to memory and JSON."""
        if not self.selected_participant:
            messagebox.showwarning("No selection", "Please select a participant first.")
            return

        parsed_weight = WeighingApp.parse_weight(self.weight_var.get())
        if parsed_weight is None:
            messagebox.showerror("Fehler", "Ungültiges Gewicht. Bitte nur Nummern eingeben.")
            self.update_save_button_state()
            return
        weight = parsed_weight

        first_name = self.val_prename.get().strip()
        last_name = self.val_surname.get().strip()
        club_txt = self.val_club.get().strip()
        birth_year_txt = self.val_birthyear.get().strip()
        full_name = f"{first_name} {last_name}".strip()

        min_age = getattr(self, "min_age_years", DEFAULT_MIN_AGE_YEARS)
        max_age = getattr(self, "max_age_years", DEFAULT_MAX_AGE_YEARS)
        parsed_year = WeighingApp.parse_birth_year(birth_year_txt, min_age, max_age)
        if not first_name or not last_name or not club_txt or parsed_year is None:
            messagebox.showerror("Fehler", "Bitte alle Felder korrekt ausfüllen.")
            self.update_save_button_state()
            return

        p = self.selected_participant
        p[WEIGHT_KEY] = weight
        p["Firstname"] = first_name
        p["Lastname"] = last_name
        p["Name"] = full_name
        p["Club"] = club_txt
        is_valid = self.valid_var.get() == "gültig"
        is_paid = self.paid_var.get() == PAID
        p["Gender"] = WeighingApp.normalize_json_gender(self.gender_var.get())
        p[VALID_KEY] = is_valid
        p[PAID_KEY] = is_paid
        p[BIRTHYEAR_KEY] = parsed_year
        if self.is_birth_year_double_start_eligible(parsed_year):
            p["mode"] = self.get_saved_double_start_mode()
        else:
            p.pop("mode", None)

        try:
            self.save_data()
            self.update_list(self.participants)
            self.saved_form_snapshot = self.get_form_snapshot()
            self.update_save_button_state()
            messagebox.showinfo("Gespeichert", f"Aktualisiert: {full_name}")
        except Exception as e:
            messagebox.showerror("Fehler", f"Daten konnten nicht gespeichert werden: {e}")

    def delete_selected_participant(self):
        """Deletes currently selected participant after explicit confirmation."""
        p = self.selected_participant
        if not p:
            messagebox.showwarning("Keine Auswahl", "Bitte zuerst einen Teilnehmer auswählen.")
            return

        first = str(p.get("Firstname") or "").strip()
        last = str(p.get("Lastname") or "").strip()
        name = f"{first} {last}".strip() or str(p.get("Name") or "Unbekannt").strip()

        confirmed = messagebox.askyesno(
            "Teilnehmer löschen",
            f"Willst du wirklich {name} unwiderruflich löschen?",
        )
        if not confirmed:
            return

        try:
            self.participants = [entry for entry in self.participants if entry is not p]
            self.search_var.set("")
            self.update_list(self.participants)
            self.listbox.selection_clear(0, tk.END)
            self.clear_participant_details()
            self.hide_duplicate_warning()
            self.save_data()
            messagebox.showinfo("Gelöscht", f"{name} wurde gelöscht.")
        except Exception as e:
            messagebox.showerror("Fehler", f"Teilnehmer konnte nicht gelöscht werden: {e}")

    def open_add_participant_window(self):
        """Opens a dialog to manually create a new participant."""

        if self.add_participant_popup and self.add_participant_popup.winfo_exists():
            self.add_participant_popup.lift()
            self.add_participant_popup.focus_force()
            return

        popup = tk.Toplevel(self)
        popup.title("Neuen Teilnehmer hinzufügen")
        popup.geometry("460x480")
        popup.configure(bg=THEME["bg"])
        self.add_participant_popup = popup

        popup.columnconfigure(1, weight=1)

        lbl_style = {"bg": THEME["bg"], "fg": THEME["fg"], "font": ("Rubik", 11)}
        entry_style = {
            "bg": THEME["input_bg"],
            "fg": "#f0f0f2",
            "font": ("Rubik", 11),
            "insertbackground": "#f0f0f2"
        }

        radio_style = {
            "bg": THEME["bg"],
            "fg": THEME["fg"],
            "selectcolor": THEME["secondary"],
            "anchor": "w",
            "font": ("Rubik", 11),
            "width": 12, 
        }

        row = 0
        padding_y = 10

        tk.Label(popup, text="Vorname", **lbl_style).grid(
            row=row, column=0, padx=20, pady=(40, 10), sticky="w"
        )
        e_first = tk.Entry(popup, **entry_style)
        e_first.grid(row=row, column=1, padx=20, pady=(40, 10), sticky="ew")
        row += 1

        tk.Label(popup, text="Nachname", **lbl_style).grid(
            row=row, column=0, padx=20, pady=padding_y, sticky="w"
        )
        e_last = tk.Entry(popup, **entry_style)
        e_last.grid(row=row, column=1, padx=20, pady=padding_y, sticky="ew")
        row += 1

        tk.Label(popup, text="Verein", **lbl_style).grid(
            row=row, column=0, padx=20, pady=padding_y, sticky="w"
        )
        e_club = tk.Entry(popup, **entry_style)
        e_club.grid(row=row, column=1, padx=20, pady=padding_y, sticky="ew")
        row += 1

        tk.Label(popup, text="Geburtsjahr", **lbl_style).grid(
            row=row, column=0, padx=20, pady=padding_y, sticky="w"
        )
        e_birthyear = tk.Entry(popup, **entry_style)
        e_birthyear.grid(row=row, column=1, padx=20, pady=padding_y, sticky="ew")
        row += 1

        tk.Label(popup, text="Geschlecht", **lbl_style).grid(
            row=row, column=0, padx=20, pady=padding_y, sticky="w"
        )

        gender_var = tk.StringVar(value="männlich")

        g_frame = tk.Frame(popup, bg=THEME["bg"])
        g_frame.grid(row=row, column=1, padx=20, pady=padding_y, sticky="w")

        tk.Radiobutton(
            g_frame,
            text="männlich",
            variable=gender_var,
            value="männlich",
            **radio_style
        ).pack(side=tk.LEFT, padx=5)

        tk.Radiobutton(
            g_frame,
            text="weiblich",
            variable=gender_var,
            value="weiblich",
            **radio_style
        ).pack(side=tk.LEFT, padx=5)

        row += 1

        tk.Label(popup, text="Gültigkeit", **lbl_style).grid(
            row=row, column=0, padx=20, pady=padding_y, sticky="w"
        )

        valid_var = tk.StringVar(value="ungültig")

        valid_frame = tk.Frame(popup, bg=THEME["bg"])
        valid_frame.grid(row=row, column=1, padx=20, pady=padding_y, sticky="w")

        tk.Radiobutton(
            valid_frame,
            text="gültig",
            variable=valid_var,
            value="gültig",
            **radio_style
        ).pack(side=tk.LEFT, padx=5)

        tk.Radiobutton(
            valid_frame,
            text="ungültig",
            variable=valid_var,
            value="ungültig",
            **radio_style
        ).pack(side=tk.LEFT, padx=5)

        row += 1

        tk.Label(popup, text="Zahlung", **lbl_style).grid(
            row=row, column=0, padx=20, pady=padding_y, sticky="w"
        )

        paid_var = tk.StringVar(value=UNPAID)

        paid_frame = tk.Frame(popup, bg=THEME["bg"])
        paid_frame.grid(row=row, column=1, padx=20, pady=padding_y, sticky="w")

        tk.Radiobutton(
            paid_frame,
            text=PAID,
            variable=paid_var,
            value=PAID,
            **radio_style
        ).pack(side=tk.LEFT, padx=5)

        tk.Radiobutton(
            paid_frame,
            text=UNPAID,
            variable=paid_var,
            value=UNPAID,
            **radio_style
        ).pack(side=tk.LEFT, padx=5)

        row += 1

        button_frame = tk.Frame(popup, bg=THEME["bg"])
        button_frame.grid(row=row, column=0, columnspan=2, pady=25)

        tk.Button(
            button_frame,
            text="Speichern",
            command=lambda: self.save_new_participant(
                popup, e_first, e_last, e_club, e_birthyear,
                gender_var, valid_var, paid_var
            ),
            bg=THEME["success"],
            fg="black",
            font=("Rubik", 10, "bold"),
            width=12,
        ).pack(side=tk.LEFT, padx=8)

        tk.Button(
            button_frame,
            text="Abbrechen",
            command=popup.destroy,
            bg=THEME["error"],
            fg="#f0f0f2",
            font=("Rubik", 10, "bold"),
            width=12,
        ).pack(side=tk.LEFT, padx=8)

        self.add_participant_fields = {
            "e_first": e_first,
            "e_last": e_last,
            "e_club": e_club,
            "e_birthyear": e_birthyear,
            "gender_var": gender_var,
            "valid_var": valid_var,
            "paid_var": paid_var,
        }

        def _on_popup_close():
            self.add_participant_popup = None
            self.add_participant_fields = {}
            popup.destroy()

        popup.protocol("WM_DELETE_WINDOW", _on_popup_close)

    def save_new_participant(self, popup, e_first, e_last, e_club, e_birthyear, gender_var, valid_var, paid_var):
        """Validates and stores a new participant."""
        first = e_first.get().strip()
        last = e_last.get().strip()
        club = e_club.get().strip()
        birth_year_txt = e_birthyear.get().strip()
        gender = gender_var.get()
        is_valid = valid_var.get() == "gültig"
        is_paid = paid_var.get() == PAID

        if not first or not last:
            messagebox.showwarning("Missing fields", "First name and last name are required.", parent=popup)
            return

        min_age = getattr(self, "min_age_years", DEFAULT_MIN_AGE_YEARS)
        max_age = getattr(self, "max_age_years", DEFAULT_MAX_AGE_YEARS)
        birth_year = WeighingApp.parse_birth_year(birth_year_txt, min_age, max_age)
        if birth_year is None:
            now_year = datetime.now().year
            min_year = now_year - max_age
            max_year = now_year - min_age
            messagebox.showerror(
                "Fehler",
                f"Geburtsjahr falsch.\nBitte Jahr zwischen {min_year} und {max_year} eingeben.",
                parent=popup,
            )
            e_birthyear.focus_set()
            e_birthyear.selection_range(0, tk.END)
            return

        ids: List[int] = []
        for p in self.participants:
            raw = p.get("ID")
            if str(raw).isdigit():
                ids.append(int(raw))
        new_id = max(ids) + 1 if ids else 1

        new_p = {
            "ID": new_id,
            "Firstname": first,
            "Lastname": last,
            "Name": f"{first} {last}",
            BIRTHYEAR_KEY: birth_year,
            "Club": club if club else "Ohne Verein",
            WEIGHT_KEY: 0.0,
            VALID_KEY: is_valid,
            "Gender": WeighingApp.normalize_json_gender(gender),
            PAID_KEY: is_paid,
        }

        try:
            self.participants.append(new_p)
            self.save_data()
            self.update_list(self.participants)
            if popup == self.add_participant_popup:
                self.add_participant_popup = None
                self.add_participant_fields = {}
            popup.destroy()
            messagebox.showinfo("Gespeichert", f"Teilnehmer hinzugefügt: {first} {last}")
        except Exception as e:
            messagebox.showerror("Fehler", f"Teilnehmer konnte nicht gespeichert werden: {e}", parent=popup)

    def open_settings_window(self):
        """Opens a dialog to configure app settings."""
        if self.settings_popup and self.settings_popup.winfo_exists():
            self.settings_popup.lift()
            self.settings_popup.focus_force()
            return

        popup_w = 520
        popup_h = 360
        popup = tk.Toplevel(self)
        self.settings_popup = popup
        popup.title("Einstellungen")
        popup.geometry(f"{popup_w}x{popup_h}")
        popup.configure(bg=THEME["bg"])
        popup.resizable(False, False)
        if hasattr(popup, "transient"):
            popup.transient(self)

        if hasattr(popup, "update_idletasks"):
            popup.update_idletasks()
        try:
            if hasattr(self, "update_idletasks"):
                self.update_idletasks()
            root_x = self.winfo_rootx()
            root_y = self.winfo_rooty()
            root_w = self.winfo_width()
            root_h = self.winfo_height()
            x_pos = root_x + (root_w - popup_w) // 2
            y_pos = root_y + (root_h - popup_h) // 2
        except Exception:
            screen_w = popup.winfo_screenwidth() if hasattr(popup, "winfo_screenwidth") else popup_w
            screen_h = popup.winfo_screenheight() if hasattr(popup, "winfo_screenheight") else popup_h
            x_pos = (screen_w - popup_w) // 2
            y_pos = (screen_h - popup_h) // 2
        popup.geometry(f"{popup_w}x{popup_h}+{max(x_pos, 0)}+{max(y_pos, 0)}")

        lbl_style = {"bg": THEME["bg"], "fg": THEME["fg"], "font": ("Rubik", 11)}

        tk.Label(popup, text="Nachkommastellen für Waage", **lbl_style).pack(pady=(22, 8))

        decimal_var = tk.StringVar(value=str(self.weight_decimal_places))
        decimal_entry = tk.Entry(
            popup,
            textvariable=decimal_var,
            bg=THEME["input_bg"],
            fg=THEME["fg"],
            insertbackground=THEME["fg"],
            font=("Rubik", 11, "bold"),
            justify="center",
            width=12,
        )
        decimal_entry.pack()

        def validate_decimal_input(proposed: str) -> bool:
            return proposed == "" or proposed.isdigit()

        decimal_entry.config(
            validate="key",
            validatecommand=(popup.register(validate_decimal_input), "%P"),
        )

        note = (
            "Beispiel: Eingang 7564 bei 2 Nachkommastellen\n"
            "wird zu 75.64 kg."
        )
        tk.Label(popup, text=note, bg=THEME["bg"], fg="gray", font=("Rubik", 10), justify="center").pack(pady=(12, 8))

        tk.Label(popup, text="Datenquelle", **lbl_style).pack(pady=(8, 6))
        path_label = tk.Label(
            popup,
            text=self.data_file_path if self.data_file_path else "Keine Datenquelle ausgewählt",
            bg=THEME["bg"],
            fg="gray",
            font=("Rubik", 9),
            wraplength=470,
            justify="center",
        )
        path_label.pack(padx=15)

        def choose_data_file():
            selected_path = filedialog.askopenfilename(
                parent=popup,
                title="Daten laden",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
            if not selected_path:
                return

            try:
                with open(selected_path, "r", encoding="utf-8-sig") as f:
                    payload = json.load(f)
                if not isinstance(payload, (list, dict)):
                    raise ValueError("Unsupported data format.")
            except Exception as e:
                messagebox.showerror("Error", f"Could not load selected file: {e}", parent=popup)
                return

            self.data_file_path = selected_path
            self.load_data()
            path_label.config(text=self.data_file_path)

        tk.Button(
            popup,
            text="Daten laden",
            command=choose_data_file,
            bg=THEME["input_bg"],
            fg="#f0f0f2",
            font=("Rubik", 10, "bold"),
            width=20,
        ).pack(pady=(8, 20))

        tk.Button(
            popup,
            text="Kamera auswählen",
            command=self.open_camera_target_dialog,
            bg=THEME["input_bg"],
            fg="#f0f0f2",
            font=("Rubik", 10, "bold"),
            width=20,
        ).pack(pady=(4, 12))

        def _on_settings_close():
            if popup == self.settings_popup:
                self.settings_popup = None
            popup.destroy()

        def save_and_close():
            decimal_text = decimal_var.get().strip()
            if not decimal_text:
                messagebox.showerror(
                    "Einstellungen",
                    "Nachkommastellen muss eine ganze Zahl größer oder gleich 0 sein.",
                    parent=popup,
                )
                decimal_entry.focus_set()
                return

            try:
                selected_places = int(decimal_text)
            except ValueError:
                messagebox.showerror(
                    "Einstellungen",
                    "Nachkommastellen muss eine ganze Zahl größer oder gleich 0 sein.",
                    parent=popup,
                )
                decimal_entry.focus_set()
                return

            if selected_places < 0:
                messagebox.showerror(
                    "Einstellungen",
                    "Nachkommastellen muss eine ganze Zahl größer oder gleich 0 sein.",
                    parent=popup,
                )
                decimal_entry.focus_set()
                return

            self.weight_decimal_places = selected_places

            if self.pending_received_weight is not None and self.weight_popup is not None and self.weight_popup.winfo_exists():
                self.show_weight_popup(self.pending_received_weight)

            _on_settings_close()

        button_frame = tk.Frame(popup, bg=THEME["bg"])
        button_frame.pack(pady=10)

        tk.Button(
            button_frame,
            text="Speichern",
            command=save_and_close,
            bg=THEME["success"],
            fg="black",
            font=("Rubik", 10, "bold"),
            width=12,
        ).pack(side=tk.LEFT, padx=8)

        tk.Button(
            button_frame,
            text="Abbrechen",
            command=_on_settings_close,
            bg=THEME["error"],
            fg="#f0f0f2",
            font=("Rubik", 10, "bold"),
            width=12,
        ).pack(side=tk.LEFT, padx=8)
        popup.protocol("WM_DELETE_WINDOW", _on_settings_close)

    def request_camera_selection(self, target_role: str):
        """Asks a connected client to open its camera selection dialog."""
        if not self.ws_loop:
            return
        asyncio.run_coroutine_threadsafe(
            self._send_camera_selection_request(target_role),
            self.ws_loop,
        )

    def open_camera_target_dialog(self):
        """Opens a small dialog to choose the target device."""
        parent = self.settings_popup if self.settings_popup and self.settings_popup.winfo_exists() else self
        popup_w = 260
        popup_h = 150
        popup = tk.Toplevel(parent)
        popup.title("Kamera auswählen")
        popup.geometry(f"{popup_w}x{popup_h}")
        popup.configure(bg=THEME["bg"])
        popup.resizable(False, False)
        if hasattr(popup, "transient"):
            popup.transient(parent)
        popup.grab_set()

        popup.update_idletasks()
        try:
            parent.update_idletasks()
            root_x = parent.winfo_rootx()
            root_y = parent.winfo_rooty()
            root_w = parent.winfo_width()
            root_h = parent.winfo_height()
            x_pos = root_x + (root_w - popup_w) // 2
            y_pos = root_y + (root_h - popup_h) // 2
        except Exception:
            screen_w = popup.winfo_screenwidth()
            screen_h = popup.winfo_screenheight()
            x_pos = (screen_w - popup_w) // 2
            y_pos = (screen_h - popup_h) // 2
        popup.geometry(f"{popup_w}x{popup_h}+{max(x_pos, 0)}+{max(y_pos, 0)}")

        tk.Label(
            popup,
            text="Für welches Gerät?",
            bg=THEME["bg"],
            fg=THEME["fg"],
            font=("Rubik", 11),
        ).pack(pady=(18, 14))

        button_frame = tk.Frame(popup, bg=THEME["bg"])
        button_frame.pack()

        def choose_target(target_role: str):
            popup.destroy()
            self.request_camera_selection(target_role)

        tk.Button(
            button_frame,
            text="Waage",
            command=lambda: choose_target("weight"),
            bg=THEME["input_bg"],
            fg="#f0f0f2",
            font=("Rubik", 10, "bold"),
            width=10,
        ).pack(side=tk.LEFT, padx=6)

        tk.Button(
            button_frame,
            text="Scanner",
            command=lambda: choose_target("scanner"),
            bg=THEME["input_bg"],
            fg="#f0f0f2",
            font=("Rubik", 10, "bold"),
            width=10,
        ).pack(side=tk.LEFT, padx=6)

        popup.protocol("WM_DELETE_WINDOW", popup.destroy)

    async def _send_camera_selection_request(self, target_role: str):
        """Sends OPEN_CAMERA_SELECTION to the requested client type."""
        if target_role == "weight":
            candidate_clients = list(self.weight_ws_clients)
            target_label = "Waage"
        elif target_role == "scanner":
            candidate_clients = list(self.scanner_ws_clients)
            target_label = "QR Scanner"
        else:
            return

        if not candidate_clients:
            self.after(
                0,
                lambda: messagebox.showwarning(
                    "Kamera",
                    f"Kein verbundener Client für {target_label} gefunden.",
                    parent=self.settings_popup if self.settings_popup and self.settings_popup.winfo_exists() else self,
                ),
            )
            return

        if target_role == "scanner" and len(candidate_clients) > 1:
            print(
                f"[WebSocket] Multiple scanner clients connected ({len(candidate_clients)}); "
                "sending camera selection request to one client only."
            )
            candidate_clients = candidate_clients[:1]

        msg = json.dumps({"type": "OPEN_CAMERA_SELECTION"}, ensure_ascii=False)
        stale = []
        for client in candidate_clients:
            try:
                await client.send(msg)
            except Exception:
                stale.append(client)

        for client in stale:
            self.weight_ws_clients.discard(client)
            self.scanner_ws_clients.discard(client)
            self.qr_ws_clients.discard(client)
            self.ws_clients.discard(client)

    def start_websocket_server(self):
        """Starts the GUI WebSocket server on ws://localhost:8765."""
        if websockets is None:
            messagebox.showwarning(
                "WebSocket",
                "Package 'websockets' not installed. Server was not started.",
            )
            return
        if self.ws_thread and self.ws_thread.is_alive():
            return

        self.ws_thread = threading.Thread(target=self._run_websocket_loop, daemon=True)
        self.ws_thread.start()

    def _run_websocket_loop(self):
        """Runs asyncio event loop for the WebSocket server in a background thread."""
        self.ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.ws_loop)
        try:
            self.ws_server = self.ws_loop.run_until_complete(self._start_ws_server())
            print(f"[WebSocket] Server running on ws://{WS_HOST}:{WS_PORT}")
            self.ws_loop.run_forever()
        except Exception as e:
            print(f"[WebSocket] Server start failed: {e}")
        finally:
            try:
                pending = asyncio.all_tasks(self.ws_loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self.ws_loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            self.ws_loop.close()

    async def _start_ws_server(self):
        """Starts websockets.serve inside a running event loop."""
        return await websockets.serve(self._ws_handler, WS_HOST, WS_PORT)

    async def _ws_handler(self, websocket, path=None):
        """Handles inbound messages from connected clients."""
        self.ws_clients.add(websocket)
        try:
            await websocket.send(
                json.dumps({"type": "SERVER_READY", "message": "GUI server connected"})
            )
            async for message in websocket:
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    await websocket.send(
                        json.dumps({"type": "error", "message": "invalid json"})
                    )
                    continue

                msg_type = payload.get("type")
                if msg_type == "register":
                    role = str(payload.get("role") or "").strip().lower()
                    self.weight_ws_clients.discard(websocket)
                    self.scanner_ws_clients.discard(websocket)
                    self.qr_ws_clients.discard(websocket)
                    if role == "weight":
                        self.weight_ws_clients.add(websocket)
                    elif role == "scanner":
                        self.scanner_ws_clients.add(websocket)
                        self.qr_ws_clients.add(websocket)
                    else:
                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "error",
                                    "message": "unsupported register role",
                                }
                            )
                        )
                        continue
                    await websocket.send(
                        json.dumps({"type": "ack", "message": f"registered as {role}"})
                    )
                    continue

                if msg_type == "qr":
                    self.qr_ws_clients.add(websocket)
                    msg_info = payload.get("info")
                    qr_data = self.filter_qr(msg_info)
                    self.after(0, lambda data=qr_data: self.handle_incoming_qr(data))
                    print(f"[WebSocket] QR: {qr_data}")
                    continue

                elif msg_type != "weight":
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "error",
                                "message": "unsupported type, expected 'weight'",
                            }
                        )
                    )
                    continue
                
                raw_weight = payload.get("weight")
                if isinstance(raw_weight, bool):
                    raw_weight = None
                if isinstance(raw_weight, float) and raw_weight.is_integer():
                    raw_weight = int(raw_weight)
                if isinstance(raw_weight, str) and raw_weight.isdigit():
                    raw_weight = int(raw_weight)

                if not isinstance(raw_weight, int):
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "error",
                                "message": "field 'weight' must be int",
                            }
                        )
                    )
                    continue

                print(f"[WebSocket] Received weight: {raw_weight}")
                self.after(0, lambda w=raw_weight: self.apply_received_weight(w))
                await websocket.send(
                    json.dumps(
                        {"type": "ack", "message": "weight accepted", "weight": raw_weight}
                    )
                )
        except Exception as e:
            print(f"[WebSocket] Client error: {e}")
        finally:
            self.weight_ws_clients.discard(websocket)
            self.scanner_ws_clients.discard(websocket)
            self.qr_ws_clients.discard(websocket)
            self.ws_clients.discard(websocket)

    def apply_received_weight(self, weight: int):
        """Stores externally received weight and shows confirmation popup."""
        self.pending_received_weight = weight
        self.show_weight_popup(weight)

    def get_selected_full_name(self) -> str:
        """Returns best available full name for the currently selected participant."""
        p = self.selected_participant
        if not p:
            return "Keine Person ausgewählt"

        first = str(p.get("Firstname") or "").strip()
        last = str(p.get("Lastname") or "").strip()
        if first and last:
            return f"{last}, {first}"
        if first or last:
            return f"{first} {last}".strip()
        return str(p.get("Name") or "Unbekannt").strip()

    def show_weight_popup(self, weight: int):
        """Shows or updates a popup with selected person name and large weight value."""
        name = self.get_selected_full_name()
        display_weight = self.format_scale_weight(weight)
        popup_w = 520
        popup_h = 300

        def center_weight_popup(popup_window):
            popup_window.update_idletasks()
            try:
                self.update_idletasks()
                root_x = self.winfo_rootx()
                root_y = self.winfo_rooty()
                root_w = self.winfo_width()
                root_h = self.winfo_height()
                x_pos = root_x + (root_w - popup_w) // 2
                y_pos = root_y + (root_h - popup_h) // 2
            except Exception:
                screen_w = popup_window.winfo_screenwidth()
                screen_h = popup_window.winfo_screenheight()
                x_pos = (screen_w - popup_w) // 2
                y_pos = (screen_h - popup_h) // 2
            popup_window.geometry(f"{popup_w}x{popup_h}+{max(x_pos, 0)}+{max(y_pos, 0)}")

        if self.weight_popup is None or not self.weight_popup.winfo_exists():
            popup = tk.Toplevel(self)
            popup.title("Waage")
            popup.geometry(f"{popup_w}x{popup_h}")
            popup.configure(bg=THEME["bg"])
            popup.resizable(False, False)
            popup.transient(self)
            popup.protocol("WM_DELETE_WINDOW", lambda: None)
            center_weight_popup(popup)

            name_label = tk.Label(
                popup,
                text=name,
                bg=THEME["bg"],
                fg=THEME["fg"],
                font=("Rubik", 14),
            )
            name_label.pack(pady=(22, 8))

            weight_label = tk.Label(
                popup,
                text=f"{display_weight} kg",
                bg=THEME["bg"],
                fg=THEME["fg"],
                font=("Rubik", 64, "bold"),
            )
            weight_label.pack(expand=True)

            hint_label = tk.Label(
                popup,
                text="Gewicht Übernehmen?",
                bg=THEME["bg"],
                fg="gray",
                font=("Rubik", 10),
            )
            hint_label.pack(pady=(0, 8))

            button_frame = tk.Frame(popup, bg=THEME["bg"])
            button_frame.pack(pady=(0, 16))

            tk.Button(
                button_frame,
                text="OK",
                command=self.accept_pending_weight,
                bg=THEME["success"],
                fg="black",
                font=("Rubik", 10, "bold"),
                width=10,
            ).pack(side=tk.LEFT, padx=8)

            tk.Button(
                button_frame,
                text="Cancel",
                command=self.cancel_pending_weight,
                bg=THEME["error"],
                fg="#f0f0f2",
                font=("Rubik", 10, "bold"),
                width=10,
            ).pack(side=tk.LEFT, padx=8)

            self.weight_popup = popup
            self.weight_popup_name_label = name_label
            self.weight_popup_value_label = weight_label
            return

        self.weight_popup_name_label.config(text=name)
        self.weight_popup_value_label.config(text=f"{display_weight} kg")
        center_weight_popup(self.weight_popup)
        self.weight_popup.deiconify()
        self.weight_popup.lift()

    def close_weight_popup(self):
        """Closes the pending weight popup if open."""
        if self.weight_popup is not None and self.weight_popup.winfo_exists():
            self.weight_popup.destroy()
        self.weight_popup = None
        self.weight_popup_name_label = None
        self.weight_popup_value_label = None

    def send_weight_request(self):
        """Sends REQUEST_WEIGHT only to non-QR WebSocket clients."""
        if not self.ws_loop or not self.ws_clients:
            return
        asyncio.run_coroutine_threadsafe(self._send_weight_request(), self.ws_loop)

    async def _send_weight_request(self):
        """Async helper to request a weight value from the connected scale client."""
        candidate_clients = [client for client in self.ws_clients if client not in self.qr_ws_clients]
        if not candidate_clients:
            return
        msg = json.dumps({"type": "REQUEST_WEIGHT"}, ensure_ascii=False)
        stale = []
        for client in candidate_clients:
            try:
                await client.send(msg)
            except Exception:
                stale.append(client)
        for client in stale:
            self.qr_ws_clients.discard(client)
            self.ws_clients.discard(client)

    def stop_websocket_server(self):
        """Stops the WebSocket server and closes all client connections."""
        if not self.ws_loop:
            return

        async def _shutdown():
            for client in self.ws_clients:
                try:
                    await client.close()
                except Exception:
                    pass
            self.ws_clients.clear()
            if self.ws_server is not None:
                self.ws_server.close()
                await self.ws_server.wait_closed()

        try:
            fut = asyncio.run_coroutine_threadsafe(_shutdown(), self.ws_loop)
            fut.result(timeout=2)
        except Exception:
            pass
        finally:
            self.ws_loop.call_soon_threadsafe(self.ws_loop.stop)

    def on_close(self):
        """Handles GUI shutdown."""
        try:
            self.unbind_all("<Control-s>")
            self.unbind_all("<Control-S>")
            self.unbind_all("<Return>")
        except Exception:
            pass
        self.close_weight_popup()
        self.stop_websocket_server()
        self.destroy()


    def create_layout(self):
        """Constructs the visual layout of the application."""
        
        # --- Sidebar (Left Panel) ---
        sidebar = tk.Frame(self, bg=THEME["secondary"], width=300)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)


        # Search Input
        self.search_var = tk.StringVar()
        self.search_var.trace("w", self.filter_list)
        search_entry = tk.Entry(sidebar, textvariable=self.search_var, bg=THEME["input_bg"], 
                                fg=THEME["input_fg"], insertbackground="#f0f0f2", font=("Rubik", 12))
        search_entry.pack(fill=tk.X, padx=10, pady=(18, 20), ipady=6)


        # Participant Listbox 
        list_frame = tk.Frame(sidebar, bg=THEME["secondary"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        entry_scrollbar = tk.Scrollbar(list_frame)
        entry_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.listbox = tk.Listbox(list_frame, bg=THEME["input_bg"], fg=THEME["input_fg"], 
                                  font=("Rubik", 14), selectbackground=THEME["accent"],
                                  yscrollcommand=entry_scrollbar.set, borderwidth=0,
                                  selectborderwidth=2)
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=(6, 2), pady=12)
        entry_scrollbar.config(command=self.listbox.yview)
        
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        # --- Main Content (Right Panel) ---
        self.main_container = tk.Frame(self, bg=THEME["bg"])
        self.main_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Create Action Buttons Button BEFORE the expanding center box
        self.create_action_buttons()

        container = self.main_container

        # Central Information Box
        box_frame = tk.Frame(
            container,
            bg=THEME["bg"],
            highlightbackground="#f0f0f2",
            highlightcolor="#f0f0f2",
            highlightthickness=2,
        )
        self.details_box_frame = box_frame
        box_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 40))
        self.save_state_hint_label = tk.Label(
            box_frame,
            text="",
            bg=THEME["bg"],
            fg="#f0f0f2",
            font=("Rubik", 11, "bold"),
            anchor="center",
            justify="center",
        )
        self.save_state_hint_label.place(relx=0.5, y=8, anchor="n")

        box_frame.columnconfigure(0, weight=1)
        box_frame.columnconfigure(1, weight=1)

        # --- Grid Elements ---
        
        # Row 0: Labels for Name
        self.create_label(box_frame, "Vorname:", 0, 0, pady=(60, 0))
        self.create_label(box_frame, "Nachname:", 0, 1, pady=(60, 0))

        # Row 1: Editable Name Fields
        self.val_prename = self.create_entry_value(box_frame, 1, 0)
        self.val_surname = self.create_entry_value(box_frame, 1, 1)

        # Row 2: Weight and Age Labels
        self.create_label(box_frame, "Gewicht (kg):", 2, 0)
        self.create_label(box_frame, "Verein:", 2, 1)

        # Row 3: Weight Entry and Age Display
        self.weight_var = self.create_entry_value(box_frame, 3, 0)
        self.val_club = self.create_entry_value(box_frame, 3, 1)

        tolerance_row = tk.Frame(box_frame, bg=THEME["bg"])
        tolerance_row.grid(row=4, column=0, padx=14, pady=(0, 10), sticky="n")
        self.tolerance_hint_prefix_label = tk.Label(
            tolerance_row,
            text="",
            bg=THEME["bg"],
            fg="#f0f0f2",
            font=("Rubik", 12, "bold"),
            width=20,
            anchor="w",
            justify="left",
        )
        self.tolerance_hint_prefix_label.grid(row=0, column=0, sticky="w")
        self.tolerance_hint_value_label = tk.Label(
            tolerance_row,
            text="",
            bg=THEME["bg"],
            fg="#f0f0f2",
            font=("Rubik", 12, "bold"),
            anchor="w",
            justify="left",
        )
        self.tolerance_hint_value_label.grid(row=0, column=1, sticky="w")

        # Row 5: Birth year and gender labels
        self.create_label(box_frame, "Geburtsjahr:", 5, 0, pady=(12, 0))
        self.create_label(box_frame, "Geschlecht:", 5, 1, pady=(12, 0))
        
        # Row 6: Editable birth year field
        self.val_birthyear = self.create_entry_value(box_frame, 6, 0)
        self.gender_var = tk.StringVar()
        self.val_gender = self.create_status_dropdown(
            box_frame, self.gender_var, ["männlich", "weiblich"], 6, 1
        )

        # Row 7: Status Labels
        self.create_label(box_frame, "Gültigkeit:", 7, 0)
        self.create_label(box_frame, "Zahlung:", 7, 1)
        
        # Row 8: Status Values (Color-coded)
        self.valid_var = tk.StringVar(value="ungültig")
        self.paid_var = tk.StringVar(value=UNPAID)
        self.val_valid = self.create_status_dropdown(
            box_frame, self.valid_var, ["gültig", "ungültig"], 8, 0
        )
        self.val_paid = self.create_status_dropdown(
            box_frame, self.paid_var, [PAID, UNPAID], 8, 1
        )
        self.valid_var.trace_add("write", self.update_status_dropdown_colors)
        self.paid_var.trace_add("write", self.update_status_dropdown_colors)
        self.gender_var.trace_add("write", self.update_status_dropdown_colors)
        tolerance_callback = getattr(self, "update_tolerance_label", None)
        if callable(tolerance_callback):
            self.gender_var.trace_add("write", tolerance_callback)
        self.update_status_dropdown_colors()
        if callable(tolerance_callback):
            self.val_birthyear.bind("<KeyRelease>", tolerance_callback)
            self.val_birthyear.bind("<FocusOut>", tolerance_callback)
        double_start_callback = getattr(self, "update_double_start_visibility", None)
        if callable(double_start_callback):
            self.val_birthyear.bind("<KeyRelease>", double_start_callback)
            self.val_birthyear.bind("<FocusOut>", double_start_callback)

        self.double_start_status_label = tk.Label(
            box_frame,
            text=f"Doppelstart: {self.double_start_mode}",
            bg=THEME["bg"],
            fg="#FFD54A",
            font=("Rubik", 13, "bold"),
            anchor="center",
            justify="center",
        )
        self.double_start_status_label.grid(row=9, column=0, columnspan=2, padx=14, pady=(16, 6), sticky="n")

        box_frame.rowconfigure(10, weight=1)
        hint_frame = tk.Frame(box_frame, bg=THEME["accent"], bd=0)
        hint_frame.grid(row=10, column=0, columnspan=2, padx=14, pady=(8, 18), sticky="sew")
        scan_hint_label = tk.Label(
            hint_frame,
            text="Drücke F12 oder hier um den QR Code zu scannen",
            bg=THEME["accent"],
            fg="black",
            font=("Rubik", 11, "bold"),
            padx=10,
            pady=8,
            cursor="hand2",
        )
        scan_hint_label.pack(fill=tk.X)
        scan_hint_label.bind("<Button-1>", self.trigger_qr_scan_hotkey)
        self.update_double_start_visibility()
        for entry_widget in [self.val_prename, self.val_surname, self.weight_var, self.val_club, self.val_birthyear]:
            entry_widget.bind("<KeyRelease>", self.update_save_button_state, add="+")
            entry_widget.bind("<FocusOut>", self.update_save_button_state, add="+")

if __name__ == "__main__":
    app = WeighingApp()
    app.mainloop()
