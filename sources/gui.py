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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_JSON_FILE = os.path.abspath(os.path.join(BASE_DIR, "..", "data.json"))
SETTINGS_FILE = os.path.abspath(os.path.join(BASE_DIR, "..", "settings.json"))
WS_HOST = "localhost"
WS_PORT = 8765
WEIGHT_KEY = "Weight"
VALID_KEY = "Valid"
PAID_KEY = "Paid"
BIRTHYEAR_KEY = "Birthyear"
TEXT_KEYS = ["Firstname", "Lastname", "Name", "Club", "Gender"]
FIELD_WIDTH = 20
LABEL_WIDTH = 22
MIN_AGE_YEARS = 6
MAX_AGE_YEARS = 120

THEME = {
    "bg": "#121212",        # Background: Very dark grey
    "fg": "#FFFFFF",        # Foreground: White text
    "accent": "#BB86FC",    # Accent: Purple
    "secondary": "#2C2C2C", # Secondary: Lighter grey for panels/frames
    "input_bg": "#333333",  # Input Fields: Dark Grey
    "input_fg": "#FFFFFF",  # Input Text: White
    "success": "#03DAC6",   # Success State: Teal
    "error": "#CF6679",      # Error State: Red
    "maennlich" : "#155FFF",
    "weiblich" : "#FA60FF"
}



class WeighingApp(tk.Tk):
    
    def __init__(self):
        super().__init__()
        self.title("Judo Weighing Station")
        try:
            self.state("zoomed")
        except Exception:
            pass
        self.configure(bg=THEME["bg"])
        
        # Data Storage
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
        self.add_participant_fields: Dict[str, Any] = {}

        # WebSocket server state (GUI acts as server)
        self.ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.ws_server = None
        self.ws_clients = set()
         
        self.create_layout()
        self.load_settings()
        self.load_data()
        self.start_websocket_server()
        self.prompt_for_data_source_selection()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    
    

    def create_action_buttons(self):
        """Creates the bottom navigation and action buttons."""
        # Ensure we attach to the main container created in create_layout
        if not hasattr(self, 'main_container'):
             # Fallback if called before main_container exists (shouldn't happen)
             parent = self
             pack_side = tk.BOTTOM
        else:
             parent = self.main_container
             pack_side = tk.BOTTOM
             
        btn_container = tk.Frame(parent, bg=THEME["bg"])
        # Pack at the bottom with padding to separate from content above and window bottom
        btn_container.pack(side=pack_side, fill=tk.X, pady=(20, 30))

        btn_opts = {
            "bg": THEME["input_bg"], "fg": "white", 
            "font": ("Arial", 10, "bold"), "bd": 1, 
            "relief": "flat", "height": 2, "cursor": "hand2"
        }
        
        # Button 3: Save Weight (Update Participant)
        tk.Button(btn_container, text="Speichern", command=self.save_weight, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Button 5: Read from Scale (Mock Simulation)
        tk.Button(btn_container, text="Gewicht nehmen", command=self.read_scale, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Settings
        tk.Button(btn_container, text="Einstellungen", command=self.open_settings_window, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Add participant button aligned with other action buttons.
        add_btn_opts = dict(btn_opts)
        add_btn_opts.update(
            {
                "bg": "white",
                "fg": "black",
                "activebackground": "white",
                "activeforeground": "black",
            }
        )

        self.btn_add = tk.Button(
            btn_container,
            text="+",
            command=self.open_add_participant_window,
            width=18,
            **add_btn_opts,
        )
        self.btn_add.pack(side=tk.RIGHT, padx=5)

        delete_btn_opts = dict(btn_opts)
        delete_btn_opts.update(
            {
                "bg": THEME["error"],
                "fg": "white",
                "activebackground": THEME["error"],
                "activeforeground": "white",
            }
        )
        self.btn_delete = tk.Button(
            btn_container,
            text="-",
            command=self.delete_selected_participant,
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
            fg="white",
            font=("Arial", 14, "bold"),
            padx=20,
            pady=10,
        )
        
        self.duplicate_warning_label.pack(side=tk.LEFT)
    
        self.duplicate_warning_close_button = tk.Button(
            self.duplicate_warning_frame,
            text="x",
            command=self.hide_duplicate_warning,
            bg=THEME["error"],
            fg="white",
            activebackground=THEME["error"],
            activeforeground="white",
            bd=0,
            relief="flat",
            font=("Arial", 9, "bold"),
            padx=8,
            pady=4,
            cursor="hand2",
        )
        self.duplicate_warning_close_button.pack(side=tk.LEFT, padx=(0, 4))
        self.duplicate_warning_frame.place_forget()


    def create_label(self, parent, text, r, c):
        """Creates a standard label at the specified grid position."""
        lbl = tk.Label(
            parent,
            text=text,
            bg=THEME["bg"],
            fg=THEME["fg"],
            font=("Arial", 12, "bold"),
            anchor="w",
            width=LABEL_WIDTH,
        )
        lbl.grid(row=r, column=c, padx=20, pady=(40, 0), sticky="n")

    def create_value(self, parent, text, r, c, pady=(5, 20)):
        """Creates a read-only value label at the specified grid position."""
        lbl = tk.Label(parent, text=text, bg=THEME["bg"], fg="gray", font=("Arial", 16))
        lbl.grid(row=r, column=c, padx=20, pady=pady, sticky="n")
        return lbl

    def create_entry_value(self, parent, r, c):
        """Creates an editable entry field at the specified grid position."""
        entry = tk.Entry(parent, bg=THEME["input_bg"], fg="white", font=("Arial", 14), justify="left", width=FIELD_WIDTH)
        entry.grid(row=r, column=c, padx=20, pady=(5, 20), ipady=4, sticky="n")
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
            font=("Arial", 12, "bold"),
            width=FIELD_WIDTH,
            anchor="w",
        )
        dropdown["menu"].config(
            bg=THEME["input_bg"],
            fg=THEME["fg"],
            activebackground=THEME["accent"],
            activeforeground="black",
            font=("Arial", 11),
        )
        dropdown.grid(row=r, column=c, padx=20, pady=(5, 20), sticky="n")
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
        """Maps stored gender values to UI values (maennlich/weiblich)."""
        v = str(value or "").strip().lower()
        if v in {"m", "male", "mann", "maennlich", "maenlich"}:
            return "maennlich"
        if v in {"w", "f", "female", "frau", "weiblich"}:
            return "weiblich"
        return "weiblich"

    @staticmethod
    def normalize_json_gender(value: Any) -> str:
        """Maps UI or legacy gender values to storage values (m/w)."""
        return "m" if WeighingApp.normalize_ui_gender(value) == "maennlich" else "w"

    def update_status_dropdown_colors(self, *args):
        """Updates dropdown backgrounds to reflect status selection."""
        valid_color = THEME["success"] if self.valid_var.get() == "gueltig" else THEME["error"]
        paid_color = THEME["success"] if self.paid_var.get() == PAID else THEME["error"]
        gender_color = THEME["maennlich"] if self.gender_var.get() == "maennlich" else THEME["weiblich"]

        self.val_valid.config(bg=valid_color)
        self.val_paid.config(bg=paid_color)
        self.val_gender.config(bg=gender_color)

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
    def parse_birth_year(value: Any) -> Optional[int]:
        """Parses and validates a year value."""
        txt = str(value or "").strip()
        if not txt.isdigit():
            return None
        year = int(txt)
        now_year = datetime.now().year
        min_year = now_year - MAX_AGE_YEARS
        max_year = now_year - MIN_AGE_YEARS
        if min_year <= year <= max_year:
            return year
        return None

    def prompt_birth_year_correction(self, parent, initial_value: Any = "") -> int:
        """Shows a blocking error dialog until a valid birth year is entered."""
        now_year = datetime.now().year
        min_year = now_year - MAX_AGE_YEARS
        max_year = now_year - MIN_AGE_YEARS
        placeholder = "Bitte neues Geburtsjahr eingeben"
        result = {"year": None}
        popup_w = 420
        popup_h = 200

        popup = tk.Toplevel(parent)
        popup.title("Fehler")
        popup.geometry(f"{popup_w}x{popup_h}")
        popup.configure(bg=THEME["bg"])
        popup.resizable(False, False)
        popup.transient(parent)
        popup.update_idletasks()
        try:
            parent.update_idletasks()
            parent_x = parent.winfo_rootx()
            parent_y = parent.winfo_rooty()
            parent_w = parent.winfo_width()
            parent_h = parent.winfo_height()
            x = parent_x + (parent_w - popup_w) // 2
            y = parent_y + (parent_h - popup_h) // 2
        except Exception:
            screen_w = popup.winfo_screenwidth()
            screen_h = popup.winfo_screenheight()
            x = (screen_w - popup_w) // 2
            y = (screen_h - popup_h) // 2
        popup.geometry(f"{popup_w}x{popup_h}+{max(x, 0)}+{max(y, 0)}")
        popup.grab_set()

        tk.Label(
            popup,
            text="Fehler: Geburtsjahr falsch",
            bg=THEME["bg"],
            fg=THEME["error"],
            font=("Arial", 12, "bold"),
        ).pack(pady=(18, 8))

        tk.Label(
            popup,
            text=f"Erlaubter Bereich: {min_year} bis {max_year}",
            bg=THEME["bg"],
            fg=THEME["fg"],
            font=("Arial", 10),
        ).pack(pady=(0, 8))

        entry = tk.Entry(
            popup,
            bg=THEME["input_bg"],
            fg="#9A9A9A",
            insertbackground="white",
            font=("Arial", 11),
            justify="center",
        )
        entry.pack(fill=tk.X, padx=20, pady=(0, 8))

        initial_txt = str(initial_value or "").strip()
        if initial_txt:
            entry.delete(0, tk.END)
            entry.insert(0, initial_txt)
            entry.config(fg="white")
        else:
            entry.insert(0, placeholder)

        def on_focus_in(_event=None):
            if entry.get() == placeholder:
                entry.delete(0, tk.END)
                entry.config(fg="white")

        def on_focus_out(_event=None):
            if not entry.get().strip():
                entry.delete(0, tk.END)
                entry.insert(0, placeholder)
                entry.config(fg="#9A9A9A")

        def on_ok(_event=None):
            value = entry.get().strip()
            if value == placeholder:
                value = ""
            parsed_year = WeighingApp.parse_birth_year(value)
            if parsed_year is None:
                messagebox.showerror(
                    "Fehler",
                    f"Geburtsjahr falsch.\nBitte Jahr zwischen {min_year} und {max_year} eingeben.",
                    parent=popup,
                )
                entry.focus_set()
                entry.selection_range(0, tk.END)
                return
            result["year"] = parsed_year
            popup.grab_release()
            popup.destroy()

        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)
        entry.bind("<Return>", on_ok)
        popup.bind("<Escape>", lambda _event: "break")
        popup.protocol("WM_DELETE_WINDOW", lambda: None)

        tk.Button(
            popup,
            text="OK",
            command=on_ok,
            bg=THEME["success"],
            fg="black",
            font=("Arial", 10, "bold"),
            width=10,
        ).pack(pady=(6, 14))

        entry.focus_set()
        popup.wait_window()
        return result["year"]

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

        # Keep focus in popup for quick manual correction and saving.
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

    def apply_qr_search(self, name: str):
        """Writes QR name into search, filters list and selects first hit."""
        query = (name or "").strip()
        if not query:
            self.hide_duplicate_warning()
            return

        self.search_var.set(query) 
        filtered = self.get_filtered_participants(query)
        self.update_list(filtered)
        if len(filtered) > 1:
            self.show_duplicate_warning()
        else:
            self.hide_duplicate_warning()
        if not filtered:
            return

        self.selected_participant = filtered[0]
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(0)
        self.listbox.activate(0)
        self.listbox.see(0)
        self.show_details(filtered[0])

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
            font=("Arial", 12, "bold"),
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
            font=("Arial", 14),
        ).pack(side=tk.LEFT)
        tk.Label(
            status_frame,
            text=qr_status,
            bg=THEME["bg"],
            fg=status_color,
            font=("Arial", 20, "bold"),
        ).pack(side=tk.LEFT)

        tk.Label(
            popup,
            text="Bitte manuel ändern.",
            bg=THEME["bg"],
            fg=THEME["fg"],
            font=("Arial", 11),
        ).pack(pady=(0, 18))

        tk.Button(
            popup,
            text="OK",
            command=popup.destroy,
            bg=THEME["input_bg"],
            fg="white",
            activebackground=THEME["input_bg"],
            activeforeground="white",
            font=("Arial", 10, "bold"),
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


    def get_exact_name_matches(self, full_name: str) -> List[Dict[str, Any]]:
        """Returns participants whose full name exactly matches query."""
        target = " ".join(str(full_name).split()).strip().lower()
        if not target:
            return []

        matches = []
        for p in self.participants:
            first = str(p.get("Firstname") or "").strip()
            last = str(p.get("Lastname") or "").strip()
            candidate = f"{first} {last}".strip()
            if not candidate:
                candidate = str(p.get("Name") or "").strip()

            candidate = " ".join(candidate.split()).strip().lower()
            if candidate == target:
                matches.append(p)
        return matches

    
    def show_duplicate_warning(self):
        self.duplicate_warning_frame.place(relx=0.5, rely=0.5, anchor="center")
        self.duplicate_warning_frame.lift()
        
    def hide_duplicate_warning(self):
        self.duplicate_warning_frame.place_forget()

    def clear_participant_details(self):
        """Clears participant detail inputs in the main view."""
        self.selected_participant = None
        self.val_prename.delete(0, tk.END)
        self.val_surname.delete(0, tk.END)
        self.val_birthyear.delete(0, tk.END)
        self.val_club.delete(0, tk.END)
        self.weight_var.delete(0, tk.END)
        self.valid_var.set("ungueltig")
        self.paid_var.set(UNPAID)
        self.gender_var.set("weiblich")
        self.update_status_dropdown_colors()
    
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

        try:
            with open(self.data_file_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            raw_participants = data if isinstance(data, list) else data.get("participants", [])
            self.participants = [p for p in raw_participants if isinstance(p, dict)]
            self.update_list(self.participants)
        except Exception as e:
            messagebox.showerror("Error", f"Could not load data: {e}")         

    @staticmethod
    def fix_mojibake_text(value: Any) -> Any:
        """Repairs common UTF-8/Latin-1 mojibake like 'MÃ¼ller' -> 'Müller'."""
        if not isinstance(value, str):
            return value

        txt = value.strip()
        if not txt:
            return value

        # Only attempt repair when suspicious marker chars are present.
        if not any(marker in txt for marker in ["Ã", "â", "Â"]):
            return value

        try:
            repaired = txt.encode("latin-1").decode("utf-8")
            return repaired
        except Exception:
            return value

    def load_settings(self):
        """Applies startup defaults without loading persisted file settings."""
        self.weight_decimal_places = 0
        self.data_file_path = ""

    def prompt_for_data_source_selection(self):
        """Prompts user to choose a data source when app starts without one."""
        if self.data_file_path:
            return
        messagebox.showinfo("Achtung", "Bitte Datenquelle auswählen.")
        self.open_settings_window()

    def format_scale_weight(self, raw_weight: int) -> str:
        """Formats integer scale input based on configured decimal places."""
        places = self.weight_decimal_places if self.weight_decimal_places in [0, 1, 2, 3] else 1
        value = raw_weight / (10 ** places)
        return f"{value:.{places}f}"

    def show_details(self, p: Dict):
        """Populates the detail view with the selected participant's data."""

        
        # Name Parsing (Handle fallback logic for simplified mock data)
        full_name = str(p.get('Name', 'Unknown'))
        parts = full_name.split()
        if len(parts) > 1:
            prename = parts[0]
            surname = " ".join(parts[1:])
        else:
            prename = full_name
            surname = ""
            
        # Prefer specific columns if available
        if 'Firstname' in p and pd.notna(p['Firstname']):
             prename = p['Firstname']
             
        # Update Editable Fields
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

        self.valid_var.set("gueltig" if is_valid else "ungueltig")
        self.paid_var.set(PAID if is_paid else UNPAID)
        self.gender_var.set(ui_gender)
        self.update_status_dropdown_colors()

        weight = p.get(WEIGHT_KEY, 0.0)
        self.weight_var.delete(0, tk.END)
        self.weight_var.insert(0, str(weight))
        # self.entry_weight.focus() # Auto-focus for immediate entry

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

        self.send_ws_payload({"type": "REQUEST_WEIGHT"})

    def trigger_qr_scan_hotkey(self, _event=None):
        """Triggers scanner popup hotkey (F12) from GUI click."""
        try:
            keyboard.press_and_release("F12")
        except Exception as e:
            messagebox.showerror("QR Scan", f"F12 konnte nicht ausgelost werden: {e}")

    def accept_pending_weight(self):
        """Accepts pending weight, writes it into the field, and saves immediately."""
        if self.pending_received_weight is None:
            return
        formatted_weight = self.format_scale_weight(self.pending_received_weight)
        self.weight_var.delete(0, tk.END)
        self.weight_var.insert(0, formatted_weight)
        self.save_weight()
        self.pending_received_weight = None
        self.close_weight_popup()

    def cancel_pending_weight(self):
        """Rejects the pending weight and closes the confirmation popup."""
        self.pending_received_weight = None
        self.close_weight_popup()

    def save_weight(self):
        """Saves edited person data and weight to memory and JSON."""
        if not self.selected_participant:
            messagebox.showwarning("No selection", "Please select a participant first.")
            return

        try:
            weight = float(self.weight_var.get())
            if weight < 0:
                messagebox.showerror("Fehler", "Gewicht musst positiv sein")
                return 
        except ValueError:
            messagebox.showerror("Fehler", "ungültiges Gewicht. Bitte ausschließlich Nummern eingeben")
            return

        first_name = self.val_prename.get().strip()
        last_name = self.val_surname.get().strip()
        full_name = f"{first_name} {last_name}".strip()
        birth_year_txt = self.val_birthyear.get().strip()

        p = self.selected_participant
        p[WEIGHT_KEY] = weight
        p["Firstname"] = first_name
        p["Lastname"] = last_name
        p["Name"] = full_name
        is_valid = self.valid_var.get() == "gueltig"
        is_paid = self.paid_var.get() == PAID
        p["Gender"] = WeighingApp.normalize_json_gender(self.gender_var.get())
        p[VALID_KEY] = is_valid
        p[PAID_KEY] = is_paid
        parsed_year = WeighingApp.parse_birth_year(birth_year_txt)
        if parsed_year is None:
            parsed_year = self.prompt_birth_year_correction(self, birth_year_txt)
            self.val_birthyear.delete(0, tk.END)
            self.val_birthyear.insert(0, str(parsed_year))
        p[BIRTHYEAR_KEY] = parsed_year

        p.pop("Gewicht (kg)", None)
        p.pop("Gewicht", None)
        p.pop("Gueltigkeit", None)
        p.pop("Gueltig", None)
        p.pop("Bezahlt", None)
        p.pop("Birthdate", None)
        p.pop("Birthday", None)
        p.pop("BirthYear", None)
        p.pop("Geburtsdatum", None)
        p.pop("Geburtsjahr", None)

        try:
            self.save_data()
            self.update_list(self.participants)
            self.send_ws_payload(
                {
                    "type": "WEIGH_IN",
                    "participant_id": p.get("ID"),
                    "name": full_name,
                    "weight": weight,
                    "valid": is_valid,
                    "paid": is_paid,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            messagebox.showinfo("Saved", f"Updated: {full_name}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save data: {e}")

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
        popup.title("Add New Participant")
        popup.geometry("400x420")
        popup.configure(bg=THEME["bg"])
        self.add_participant_popup = popup

        lbl_style = {"bg": THEME["bg"], "fg": THEME["fg"], "font": ("Arial", 11)}
        entry_style = {"bg": THEME["input_bg"], "fg": "white", "font": ("Arial", 11), "insertbackground": "white"}

        tk.Label(popup, text="First Name", **lbl_style).pack(pady=(15, 5))
        e_first = tk.Entry(popup, **entry_style)
        e_first.pack(fill=tk.X, padx=20)

        tk.Label(popup, text="Last Name", **lbl_style).pack(pady=(10, 5))
        e_last = tk.Entry(popup, **entry_style)
        e_last.pack(fill=tk.X, padx=20)

        tk.Label(popup, text="Club", **lbl_style).pack(pady=(10, 5))
        e_club = tk.Entry(popup, **entry_style)
        e_club.pack(fill=tk.X, padx=20)

        tk.Label(popup, text="Birthyear", **lbl_style).pack(pady=(10, 5))
        e_birthyear = tk.Entry(popup, **entry_style)
        e_birthyear.pack(fill=tk.X, padx=20)

        tk.Label(popup, text="Gender", **lbl_style).pack(pady=(10, 5))
        gender_var = tk.StringVar(value="maennlich")
        g_frame = tk.Frame(popup, bg=THEME["bg"])
        g_frame.pack()
        tk.Radiobutton(g_frame, text="maennlich", variable=gender_var, value="maennlich",
                       bg=THEME["bg"], fg=THEME["fg"], selectcolor=THEME["secondary"]).pack(side=tk.LEFT, padx=10)
        tk.Radiobutton(g_frame, text="weiblich", variable=gender_var, value="weiblich",
                       bg=THEME["bg"], fg=THEME["fg"], selectcolor=THEME["secondary"]).pack(side=tk.LEFT, padx=10)

        button_frame = tk.Frame(popup, bg=THEME["bg"])
        button_frame.pack(pady=25)

        tk.Button(
            button_frame,
            text="Save",
            command=lambda: self.save_new_participant(
                popup, e_first, e_last, e_club, e_birthyear, gender_var
            ),
            bg=THEME["success"],
            fg="black",
            font=("Arial", 10, "bold"),
            width=12,
        ).pack(side=tk.LEFT, padx=8)

        tk.Button(
            button_frame,
            text="Cancel",
            command=popup.destroy,
            bg=THEME["error"],
            fg="white",
            font=("Arial", 10, "bold"),
            width=12,
        ).pack(side=tk.LEFT, padx=8)

        self.add_participant_fields = {
            "e_first": e_first,
            "e_last": e_last,
            "e_club": e_club,
            "e_birthyear": e_birthyear,
            "gender_var": gender_var,
        }

        def _on_popup_close():
            self.add_participant_popup = None
            self.add_participant_fields = {}
            popup.destroy()

        popup.protocol("WM_DELETE_WINDOW", _on_popup_close)

    def save_new_participant(self, popup, e_first, e_last, e_club, e_birthyear, gender_var):
        """Validates and stores a new participant."""
        first = e_first.get().strip()
        last = e_last.get().strip()
        club = e_club.get().strip()
        birth_year_txt = e_birthyear.get().strip()
        gender = gender_var.get()

        if not first or not last:
            messagebox.showwarning("Missing fields", "First name and last name are required.", parent=popup)
            return

        birth_year = WeighingApp.parse_birth_year(birth_year_txt)
        if birth_year is None:
            birth_year = self.prompt_birth_year_correction(popup, birth_year_txt)
            e_birthyear.delete(0, tk.END)
            e_birthyear.insert(0, str(birth_year))

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
            "Club": club if club else None,
            WEIGHT_KEY: 0.0,
            VALID_KEY: False,
            "Gender": WeighingApp.normalize_json_gender(gender),
            PAID_KEY: False,
        }

        try:
            self.participants.append(new_p)
            self.save_data()
            self.update_list(self.participants)
            if popup == self.add_participant_popup:
                self.add_participant_popup = None
                self.add_participant_fields = {}
            popup.destroy()
            messagebox.showinfo("Saved", f"Added participant: {first} {last}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save participant: {e}", parent=popup)

    def open_settings_window(self):
        """Opens a dialog to configure app settings."""
        popup_w = 520
        popup_h = 360
        popup = tk.Toplevel(self)
        popup.title("Einstellungen")
        popup.geometry(f"{popup_w}x{popup_h}")
        popup.configure(bg=THEME["bg"])
        popup.resizable(False, False)
        popup.transient(self)

        popup.update_idletasks()
        try:
            self.update_idletasks()
            root_x = self.winfo_rootx()
            root_y = self.winfo_rooty()
            root_w = self.winfo_width()
            root_h = self.winfo_height()
            x_pos = root_x + (root_w - popup_w) // 2
            y_pos = root_y + (root_h - popup_h) // 2
        except Exception:
            screen_w = popup.winfo_screenwidth()
            screen_h = popup.winfo_screenheight()
            x_pos = (screen_w - popup_w) // 2
            y_pos = (screen_h - popup_h) // 2
        popup.geometry(f"{popup_w}x{popup_h}+{max(x_pos, 0)}+{max(y_pos, 0)}")

        lbl_style = {"bg": THEME["bg"], "fg": THEME["fg"], "font": ("Arial", 11)}
        dropdown_style = {
            "bg": THEME["input_bg"],
            "fg": THEME["fg"],
            "activebackground": THEME["accent"],
            "activeforeground": "black",
            "highlightthickness": 0,
            "bd": 0,
            "font": ("Arial", 11, "bold"),
            "width": 10,
        }

        tk.Label(popup, text="Nachkommastellen für Waage", **lbl_style).pack(pady=(22, 8))

        decimal_var = tk.StringVar(value=str(self.weight_decimal_places))
        decimal_dropdown = tk.OptionMenu(popup, decimal_var, "0", "1", "2", "3")
        decimal_dropdown.config(**dropdown_style)
        decimal_dropdown["menu"].config(
            bg=THEME["input_bg"],
            fg=THEME["fg"],
            activebackground=THEME["accent"],
            activeforeground="black",
            font=("Arial", 10),
        )
        decimal_dropdown.pack()

        note = (
            "Beispiel: Eingang 7564 bei 2 Nachkommastellen\n"
            "wird zu 75.64 kg."
        )
        tk.Label(popup, text=note, bg=THEME["bg"], fg="gray", font=("Arial", 10), justify="center").pack(pady=(12, 8))

        tk.Label(popup, text="Datenquelle", **lbl_style).pack(pady=(8, 6))
        path_label = tk.Label(
            popup,
            text=self.data_file_path if self.data_file_path else "Keine Datenquelle ausgewählt",
            bg=THEME["bg"],
            fg="gray",
            font=("Arial", 9),
            wraplength=470,
            justify="center",
        )
        path_label.pack(padx=15)

        def choose_data_file():
            initial_dir = os.path.dirname(self.data_file_path) if self.data_file_path else os.path.dirname(DEFAULT_JSON_FILE)
            selected_path = filedialog.askopenfilename(
                parent=popup,
                title="Daten laden",
                initialdir=initial_dir,
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
            fg="white",
            font=("Arial", 10, "bold"),
            width=20,
        ).pack(pady=(8, 4))

        def save_and_close():
            try:
                selected_places = int(decimal_var.get())
            except ValueError:
                selected_places = 1

            if selected_places not in [0, 1, 2, 3]:
                selected_places = 1

            self.weight_decimal_places = selected_places

            if self.pending_received_weight is not None and self.weight_popup is not None and self.weight_popup.winfo_exists():
                self.show_weight_popup(self.pending_received_weight)

            popup.destroy()

        button_frame = tk.Frame(popup, bg=THEME["bg"])
        button_frame.pack(pady=10)

        tk.Button(
            button_frame,
            text="Save",
            command=save_and_close,
            bg=THEME["success"],
            fg="black",
            font=("Arial", 10, "bold"),
            width=12,
        ).pack(side=tk.LEFT, padx=8)

        tk.Button(
            button_frame,
            text="Cancel",
            command=popup.destroy,
            bg=THEME["error"],
            fg="white",
            font=("Arial", 10, "bold"),
            width=12,
        ).pack(side=tk.LEFT, padx=8)

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
                if msg_type == "qr":
                    msg_info = payload.get("info")
                    qr_data = self.filter_qr(msg_info)
                    self.after(0, lambda data=qr_data: self.handle_incoming_qr(data))
                    print(f"[WebSocket] QR: {qr_data}")
                    await websocket.send(
                        json.dumps({"type": "ack", "message": "qr accepted", "qr": qr_data})
                    )
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
            self.ws_clients.discard(websocket)

    def apply_received_weight(self, weight: int):
        """Stores externally received weight and shows confirmation popup."""
        self.pending_received_weight = weight
        self.show_weight_popup(weight)

    def get_selected_full_name(self) -> str:
        """Returns best available full name for the currently selected participant."""
        p = self.selected_participant
        if not p:
            return "Keine Person ausgewahlt"

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
                font=("Arial", 14),
            )
            name_label.pack(pady=(22, 8))

            weight_label = tk.Label(
                popup,
                text=f"{display_weight} kg",
                bg=THEME["bg"],
                fg=THEME["fg"],
                font=("Arial", 64, "bold"),
            )
            weight_label.pack(expand=True)

            hint_label = tk.Label(
                popup,
                text="Weight Übernehmen?",
                bg=THEME["bg"],
                fg="gray",
                font=("Arial", 10),
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
                font=("Arial", 10, "bold"),
                width=10,
            ).pack(side=tk.LEFT, padx=8)

            tk.Button(
                button_frame,
                text="Cancel",
                command=self.cancel_pending_weight,
                bg=THEME["error"],
                fg="white",
                font=("Arial", 10, "bold"),
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

    def send_ws_payload(self, payload: Dict[str, Any]):
        """Broadcasts a payload to all connected WebSocket clients."""
        if not self.ws_loop or not self.ws_clients:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast_payload(payload), self.ws_loop)

    async def _broadcast_payload(self, payload: Dict[str, Any]):
        """Async helper to broadcast JSON payloads."""
        if not self.ws_clients:
            return
        msg = json.dumps(payload, ensure_ascii=False)
        stale = []
        for client in self.ws_clients:
            try:
                await client.send(msg)
            except Exception:
                stale.append(client)
        for client in stale:
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
        self.close_weight_popup()
        self.stop_websocket_server()
        self.destroy()


    def create_layout(self):
        """Constructs the visual layout of the application."""
        
        # --- Sidebar (Left Panel) ---
        sidebar = tk.Frame(self, bg=THEME["secondary"], width=300)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False) # Prevent shrinking


        # Search Input
        self.search_var = tk.StringVar()
        self.search_var.trace("w", self.filter_list) # Bind text change to filter function
        search_entry = tk.Entry(sidebar, textvariable=self.search_var, bg=THEME["input_bg"], 
                                fg=THEME["input_fg"], insertbackground="white", font=("Arial", 12))
        search_entry.pack(fill=tk.X, padx=10, pady=(18, 20), ipady=6)


        # Participant Listbox (Scrollable)
        list_frame = tk.Frame(sidebar, bg=THEME["secondary"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        entry_scrollbar = tk.Scrollbar(list_frame)
        entry_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.listbox = tk.Listbox(list_frame, bg=THEME["input_bg"], fg=THEME["input_fg"], 
                                  font=("Arial", 14), selectbackground=THEME["accent"],
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

        container = self.main_container # Alias for existing code

        # Central Information Box
        box_frame = tk.Frame(container, bg=THEME["bg"], highlightbackground="white", highlightthickness=2)
        box_frame.pack(fill=tk.BOTH, expand=True, pady=(20, 80))

        # Grid Configuration
        box_frame.columnconfigure(0, weight=1)
        box_frame.columnconfigure(1, weight=1)

        # --- Grid Elements ---
        
        # Row 0: Labels for Name
        self.create_label(box_frame, "Vorname:", 0, 0)
        self.create_label(box_frame, "Nachname:", 0, 1)

        # Row 1: Editable Name Fields
        self.val_prename = self.create_entry_value(box_frame, 1, 0)
        self.val_surname = self.create_entry_value(box_frame, 1, 1)

        # Row 2: Weight and Age Labels
        self.create_label(box_frame, "Gewicht (kg):", 2, 0)
        self.create_label(box_frame, "Verein:", 2, 1)

        # Row 3: Weight Entry and Age Display
        self.weight_var = self.create_entry_value(box_frame, 3, 0)
        self.val_club = self.create_entry_value(box_frame, 3, 1)


        # Row 4: Birth year and gender labels
        self.create_label(box_frame, "Geburtsjahr:", 4, 0)
        self.create_label(box_frame, "Geschlecht:", 4, 1)
        
        # Row 5: Editable birth year field
        self.val_birthyear = self.create_entry_value(box_frame, 5, 0)
        self.gender_var = tk.StringVar()
        self.val_gender = self.create_status_dropdown(
            box_frame, self.gender_var, ["maennlich", "weiblich"], 5, 1
        )

        # Row 6: Status Labels
        self.create_label(box_frame, "ist gültig:", 6, 0)
        self.create_label(box_frame, "hat gezahlt:", 6, 1)
        
        # Row 7: Status Values (Color-coded)
        # Adding extra bottom padding to prevent sticking to the box border
        self.valid_var = tk.StringVar(value="ungueltig")
        self.paid_var = tk.StringVar(value=UNPAID)
        self.val_valid = self.create_status_dropdown(
            box_frame, self.valid_var, ["gueltig", "ungueltig"], 7, 0
        )
        self.val_paid = self.create_status_dropdown(
            box_frame, self.paid_var, [PAID, UNPAID], 7, 1
        )
        self.valid_var.trace_add("write", self.update_status_dropdown_colors)
        self.paid_var.trace_add("write", self.update_status_dropdown_colors)
        self.gender_var.trace_add("write", self.update_status_dropdown_colors)
        self.update_status_dropdown_colors()

        # Scan hint at the bottom of the white content box.
        hint_frame = tk.Frame(box_frame, bg=THEME["accent"], bd=0)
        hint_frame.grid(row=8, column=0, columnspan=2, padx=20, pady=(24, 10), sticky="ew")
        scan_hint_label = tk.Label(
            hint_frame,
            text="Drücke F12 um den QR Code zu scannen",
            bg=THEME["accent"],
            fg="black",
            font=("Arial", 11, "bold"),
            padx=10,
            pady=8,
            cursor="hand2",
        )
        scan_hint_label.pack(fill=tk.X)
        scan_hint_label.bind("<Button-1>", self.trigger_qr_scan_hotkey)

        # --- Action Buttons (Bottom) ---
        # self.create_action_buttons() # Moved to top




if __name__ == "__main__":
    app = WeighingApp()
    app.mainloop()

