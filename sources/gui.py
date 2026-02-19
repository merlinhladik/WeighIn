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


PAID = "Zahlung erfolgt"
UNPAID = "Zahlung offen"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_JSON_FILE = os.path.abspath(os.path.join(BASE_DIR, "..", "data.json"))
SETTINGS_FILE = os.path.abspath(os.path.join(BASE_DIR, "..", "settings.json"))
WS_HOST = "localhost"
WS_PORT = 8765
WEIGHT_KEY = "Gewicht (kg)"
VALID_KEY = "Gueltigkeit"
PAID_KEY = "Bezahlt"
BIRTHDATE_KEY = "Geburtsdatum"
TEXT_KEYS = ["Vorname", "Nachname", "Name", "Verein", "Geschlecht", BIRTHDATE_KEY]

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
        self.geometry("1100x700")
        self.configure(bg=THEME["bg"])
        
        # Data Storage
        self.participants: List[Dict[str, Any]] = []
        self.selected_participant: Optional[Dict[str, Any]] = None
        self.data_file_path: str = DEFAULT_JSON_FILE
        self.pending_received_weight: Optional[int] = None
        self.weight_decimal_places: int = 1
        self.weight_popup: Optional[tk.Toplevel] = None
        self.weight_popup_name_label: Optional[tk.Label] = None
        self.weight_popup_value_label: Optional[tk.Label] = None

        # WebSocket server state (GUI acts as server)
        self.ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.ws_server = None
        self.ws_clients = set()
         
        self.create_layout()
        self.load_settings()
        self.load_data()
        self.start_websocket_server()
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
            "relief": "flat", "height": 2
        }
        
        # Button 3: Save Weight (Update Participant)
        tk.Button(btn_container, text="Save", command=self.save_weight, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Button 5: Read from Scale (Mock Simulation)
        tk.Button(btn_container, text="take current weight", command=self.read_scale, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Settings
        tk.Button(btn_container, text="Einstellungen", command=self.open_settings_window, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Add participant as floating plus button in the lower-right corner.
        # Position can be changed via relx/rely and x/y.
        self.btn_add = tk.Button(
            self.main_container,
            text="+",
            command=self.open_add_participant_window,
            bg=THEME["fg"],
            fg="black",
            activebackground=THEME["fg"],
            activeforeground="black",
            font=("Arial", 22, "bold"),
            bd=0,
            relief="flat",
            width=3,
        )
        self.btn_add.place(relx=1.0, rely=1.0, anchor="se", x=-100, y=-50)
        self.btn_add.lift()

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
        lbl = tk.Label(parent, text=text, bg=THEME["bg"], fg=THEME["fg"], font=("Arial", 12, "bold"))
        lbl.grid(row=r, column=c, padx=20, pady=(40, 0), sticky="s")

    def create_value(self, parent, text, r, c, pady=(5, 20)):
        """Creates a read-only value label at the specified grid position."""
        lbl = tk.Label(parent, text=text, bg=THEME["bg"], fg="gray", font=("Arial", 16))
        lbl.grid(row=r, column=c, padx=20, pady=pady, sticky="n")
        return lbl

    def create_entry_value(self, parent, r, c):
        """Creates an editable entry field at the specified grid position."""
        entry = tk.Entry(parent, bg=THEME["input_bg"], fg="white", font=("Arial", 14), justify="center")
        entry.grid(row=r, column=c, padx=20, pady=(5, 20), sticky="n")
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
            width=16,
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

    def update_status_dropdown_colors(self, *args):
        """Updates dropdown backgrounds to reflect status selection."""
        valid_color = THEME["success"] if self.valid_var.get() == "gueltig" else THEME["error"]
        paid_color = THEME["success"] if self.paid_var.get() == PAID else THEME["error"]
        gender_color = THEME["maennlich"] if self.gender_var.get() == "maennlich" else THEME["weiblich"]

        self.val_valid.config(bg=valid_color)
        self.val_paid.config(bg=paid_color)
        self.val_gender.config(bg=gender_color)

    @staticmethod
    def get_birthdate_text(p: Dict[str, Any]) -> str:
        """Returns a displayable birthdate string from mixed data formats."""
        full_birthdate = p.get(BIRTHDATE_KEY)
        if full_birthdate:
            return str(full_birthdate)

        birth_year = p.get("Geburtsjahr")
        if isinstance(birth_year, int) and 1900 <= birth_year <= datetime.now().year:
            # Fallback when only the year exists.
            return f"01.01.{birth_year}"

        return "---"

    @staticmethod
    def get_birth_year_from_date(birthdate: str) -> Optional[int]:
        """Extracts birth year from DD.MM.YYYY, returns None on parse errors."""
        parts = birthdate.split(".")
        if len(parts) != 3:
            return None
        day_txt, month_txt, year_txt = parts
        if not (day_txt.isdigit() and month_txt.isdigit() and year_txt.isdigit()):
            return None

        day = int(day_txt)
        month = int(month_txt)
        year = int(year_txt)
        if not (1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= datetime.now().year):
            return None
        return year

    def filter_qr(self, info: Any) -> Dict[str, Any]:
        """Normalizes QR info and combines first/last name to one display field."""
        if not isinstance(info, dict):
            return {
                "name": "",
                "first_name": "",
                "last_name": "",
                "birth_date": None,
                "exp_timestamp": None,
            }

        first_name = str(info.get("first_name") or info.get("first") or "").strip()
        last_name = str(info.get("last_name") or info.get("last") or "").strip()
        full_name = f"{first_name} {last_name}".strip()

        return {
            "name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "birth_date": info.get("birth_date") or info.get("birthdat"),
            "exp_timestamp": info.get("exp_timestamp"),
        }
        
    
    def get_filtered_participants(self, query: str) -> List[Dict[str, Any]]:
        """Returns participants matching name or club."""
        q = (query or "").strip().lower()
        if not q:
            return self.participants
        return [
            p for p in self.participants
            if q in str(p.get("Name", "")).lower() or q in str(p.get("Verein", "")).lower()
        ]

    def apply_qr_search(self, name: str):
        """Writes QR name into search, filters list and selects first hit."""
        query = (name or "").strip()
        if not query:
            self.hide_duplicate_warning()
            return

        self.search_var.set(query)  # triggers filter_list via trace
        filtered = self.get_filtered_participants(query)
        self.update_list(filtered)
        duplicates = self.get_exact_name_matches(query)
        if len(duplicates) > 1:
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
    
    def get_exact_name_matches(self, full_name: str) -> List[Dict[str, Any]]:
        """Returns participants whose full name exactly matches query."""
        target = " ".join(str(full_name).split()).strip().lower()
        if not target:
            return []

        matches = []
        for p in self.participants:
            first = str(p.get("Vorname") or "").strip()
            last = str(p.get("Nachname") or "").strip()
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
    
    def filter_list(self, *args):
        """Filters the participant list based on the search bar input."""
        query = self.search_var.get()
        filtered = self.get_filtered_participants(query)
        self.update_list(filtered)

    def update_list(self, data: List[Dict]):
        """Refreshes the sidebar listbox with the provided data."""
        self.listbox.delete(0, tk.END)
        for p in data:
            name = p.get('Name', 'Unknown')
            p_id = p.get('ID', '?')
            self.listbox.insert(tk.END, f"{name} ({p_id})")

    def on_select(self, event):
        """Handles selection of a participant from the listbox."""
        selection = self.listbox.curselection()
        if not selection:
            return
        
        index = selection[0]
        display_text = self.listbox.get(index) # Format: "Name (ID)"
        
        try:
            # Extract ID from the display string to find the correct record
            # Assuming format always ends with "(ID)"
            p_id_str = display_text.split('(')[-1].replace(')', '')
            
            # Find matching participant
            match = next((p for p in self.participants if str(p.get('ID')) == p_id_str), None)
            
            if match:
                self.selected_participant = match
                self.show_details(match)
        except Exception:
             pass

    def load_data(self):
        """Loads participant data from the Excel file."""
        if not os.path.exists(self.data_file_path):
             messagebox.showerror("Error", f"Data file not found: {self.data_file_path}")
             return

        try:
            with open(self.data_file_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            raw_participants = data if isinstance(data, list) else data.get("participants", [])
            normalized: List[Dict[str, Any]] = []
            changed = False

            for p in raw_participants:
                if not isinstance(p, dict):
                    continue
                cleaned = self.normalize_participant(p)
                normalized.append(cleaned)
                if cleaned != p:
                    changed = True

            self.participants = normalized
            if changed:
                self.save_data()
            self.update_list(self.participants)
        except Exception as e:
            messagebox.showerror("Error", f"Could not load data: {e}")         

    @staticmethod
    def normalize_participant(p: Dict[str, Any]) -> Dict[str, Any]:
        """Normalizes participant schema to one canonical key per category."""
        result = dict(p)

        raw_weight = result.get(WEIGHT_KEY, result.get("Gewicht", 0.0))
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            weight = 0.0

        is_valid = WeighingApp.to_bool(
            result.get(VALID_KEY, result.get("Gueltig", result.get("Valid", False)))
        )
        is_paid = WeighingApp.to_bool(
            result.get(PAID_KEY, result.get("Paid", False))
        )
        birthdate = result.get(BIRTHDATE_KEY, result.get("Birthdate", ""))
        if birthdate is None:
            birthdate = ""

        for key in TEXT_KEYS:
            if key in result:
                result[key] = WeighingApp.fix_mojibake_text(result.get(key))

        result[WEIGHT_KEY] = weight
        result[VALID_KEY] = is_valid
        result[PAID_KEY] = is_paid
        result[BIRTHDATE_KEY] = str(birthdate)

        result.pop("Gewicht", None)
        result.pop("Gueltig", None)
        result.pop("Valid", None)
        result.pop("Paid", None)
        result.pop("Birthdate", None)

        return result

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
        """Loads app settings from JSON and applies safe defaults."""
        self.weight_decimal_places = 1
        self.data_file_path = DEFAULT_JSON_FILE
        if not os.path.exists(SETTINGS_FILE):
            return

        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except Exception:
            return

        value = settings.get("weight_decimal_places")
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        if isinstance(value, int) and value in [0, 1, 2, 3]:
            self.weight_decimal_places = value

        data_file = settings.get("data_file_path")
        if isinstance(data_file, str) and data_file.strip():
            self.data_file_path = data_file.strip()

    def save_settings(self):
        """Persists app settings to JSON."""
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "weight_decimal_places": self.weight_decimal_places,
                    "data_file_path": self.data_file_path,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

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
        if 'Vorname' in p and pd.notna(p['Vorname']):
             prename = p['Vorname']
             
        # Update Editable Fields
        self.val_prename.delete(0, tk.END)
        self.val_prename.insert(0, str(prename))
        
        self.val_surname.delete(0, tk.END)
        self.val_surname.insert(0, str(surname))
        
        self.val_birthdate.delete(0, tk.END)
        self.val_birthdate.insert(0, self.get_birthdate_text(p))

        self.val_club.delete(0, tk.END)
        self.val_club.insert(0, str(p.get("Verein")))
        
        
        
        

        is_valid = self.to_bool(p.get(VALID_KEY, False))
        is_paid = self.to_bool(p.get(PAID_KEY, False))
        
        gender_value = str(p.get("Geschlecht") or "").strip().lower()
        is_male = gender_value == "maennlich"

        self.valid_var.set("gueltig" if is_valid else "ungueltig")
        self.paid_var.set(PAID if is_paid else UNPAID)
        self.gender_var.set("maennlich" if is_male else "weiblich")
        self.update_status_dropdown_colors()

        weight = p.get(WEIGHT_KEY, 0.0)
        self.weight_var.delete(0, tk.END)
        self.weight_var.insert(0, str(weight))
        # self.entry_weight.focus() # Auto-focus for immediate entry

    def save_data(self):
        """Writes current participant data back to JSON."""
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

    def accept_pending_weight(self):
        """Accepts the pending received weight and writes it into the weight field."""
        if self.pending_received_weight is None:
            return
        formatted_weight = self.format_scale_weight(self.pending_received_weight)
        self.weight_var.delete(0, tk.END)
        self.weight_var.insert(0, formatted_weight)
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
        except ValueError:
            messagebox.showerror("Error", "Invalid weight. Please enter a number.")
            return

        first_name = self.val_prename.get().strip()
        last_name = self.val_surname.get().strip()
        full_name = f"{first_name} {last_name}".strip()
        birthdate = self.val_birthdate.get().strip()

        p = self.selected_participant
        p[WEIGHT_KEY] = weight
        p["Vorname"] = first_name
        p["Nachname"] = last_name
        p["Name"] = full_name
        is_valid = self.valid_var.get() == "gueltig"
        is_paid = self.paid_var.get() == PAID
        p[VALID_KEY] = is_valid
        p[PAID_KEY] = is_paid
        p[BIRTHDATE_KEY] = birthdate
        parsed_year = self.get_birth_year_from_date(birthdate)
        if parsed_year is not None:
            p["Geburtsjahr"] = parsed_year

        p.pop("Gewicht", None)
        p.pop("Gueltig", None)
        p.pop("Valid", None)
        p.pop("Paid", None)
        p.pop("Birthdate", None)

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
            messagebox.showinfo("Saved", f"Updated: {full_name}\nWeight: {weight} kg")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save data: {e}")

    def open_add_participant_window(self):
        """Opens a dialog to manually create a new participant."""
        popup = tk.Toplevel(self)
        popup.title("Add New Participant")
        popup.geometry("400x420")
        popup.configure(bg=THEME["bg"])

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

        tk.Label(popup, text="Birthdate (DD.MM.YYYY)", **lbl_style).pack(pady=(10, 5))
        e_birthdate = tk.Entry(popup, **entry_style)
        e_birthdate.pack(fill=tk.X, padx=20)

        tk.Label(popup, text="Gender", **lbl_style).pack(pady=(10, 5))
        gender_var = tk.StringVar(value="maenlich")
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
                popup, e_first, e_last, e_club, e_birthdate, gender_var
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

    def save_new_participant(self, popup, e_first, e_last, e_club, e_birthdate, gender_var):
        """Validates and stores a new participant."""
        first = e_first.get().strip()
        last = e_last.get().strip()
        club = e_club.get().strip()
        birthdate = e_birthdate.get().strip()
        gender = gender_var.get()

        if not first or not last:
            messagebox.showwarning("Missing fields", "First name and last name are required.", parent=popup)
            return

        if birthdate and self.get_birth_year_from_date(birthdate) is None:
            messagebox.showwarning("Invalid input", "Birthdate must be in format DD.MM.YYYY.", parent=popup)
            return

        birth_year = self.get_birth_year_from_date(birthdate) if birthdate else None

        ids: List[int] = []
        for p in self.participants:
            raw = p.get("ID")
            if str(raw).isdigit():
                ids.append(int(raw))
        new_id = max(ids) + 1 if ids else 1

        new_p = {
            "ID": new_id,
            "Vorname": first,
            "Nachname": last,
            "Name": f"{first} {last}",
            "Geburtsjahr": birth_year,
            BIRTHDATE_KEY: birthdate if birthdate else "",
            "Verein": club if club else None,
            WEIGHT_KEY: 0.0,
            VALID_KEY: False,
            "Geschlecht": gender,
            PAID_KEY: False,
        }

        try:
            self.participants.append(new_p)
            self.save_data()
            self.update_list(self.participants)
            popup.destroy()
            messagebox.showinfo("Saved", f"Added participant: {first} {last}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save participant: {e}", parent=popup)

    def open_settings_window(self):
        """Opens a dialog to configure app settings."""
        popup = tk.Toplevel(self)
        popup.title("Einstellungen")
        popup.geometry("520x360")
        popup.configure(bg=THEME["bg"])
        popup.resizable(False, False)

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

        tk.Label(popup, text="Nachkommastellen f?r Waage", **lbl_style).pack(pady=(22, 8))

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
            text=self.data_file_path,
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
            self.save_settings()
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
            self.save_settings()

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
                    self.after(0, lambda n=qr_data.get("name", ""): self.apply_qr_search(n))
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

        first = str(p.get("Vorname") or "").strip()
        last = str(p.get("Nachname") or "").strip()
        if first and last:
            return f"{last}, {first}"
        if first or last:
            return f"{first} {last}".strip()
        return str(p.get("Name") or "Unbekannt").strip()

    def show_weight_popup(self, weight: int):
        """Shows or updates a popup with selected person name and large weight value."""
        name = self.get_selected_full_name()
        display_weight = self.format_scale_weight(weight)
        if self.weight_popup is None or not self.weight_popup.winfo_exists():
            popup = tk.Toplevel(self)
            popup.title("Waage")
            popup.geometry("520x300")
            popup.configure(bg=THEME["bg"])
            popup.resizable(False, False)
            popup.transient(self)
            popup.protocol("WM_DELETE_WINDOW", lambda: None)

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
                text="Gewicht übernehmen?",
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
        search_entry.pack(fill=tk.X, padx=20, pady=(0, 20))


        # Participant Listbox (Scrollable)
        list_frame = tk.Frame(sidebar, bg=THEME["secondary"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        entry_scrollbar = tk.Scrollbar(list_frame)
        entry_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.listbox = tk.Listbox(list_frame, bg=THEME["input_bg"], fg=THEME["input_fg"], 
                                  font=("Arial", 11), selectbackground=THEME["accent"],
                                  yscrollcommand=entry_scrollbar.set, borderwidth=0)
        self.listbox.pack(fill=tk.BOTH, expand=True)
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
        self.create_label(box_frame, "PreName", 0, 0)
        self.create_label(box_frame, "SurName", 0, 1)

        # Row 1: Editable Name Fields
        self.val_prename = self.create_entry_value(box_frame, 1, 0)
        self.val_surname = self.create_entry_value(box_frame, 1, 1)

        # Row 2: Weight and Age Labels
        self.create_label(box_frame, "Weight (kg)", 2, 0)
        self.create_label(box_frame, "Club", 2, 1)

        # Row 3: Weight Entry and Age Display
        self.weight_var = self.create_entry_value(box_frame, 3, 0)
        self.val_club = self.create_entry_value(box_frame, 3, 1)


        # Row 4: Birthday and Gender Labels
        self.create_label(box_frame, "Birthdate", 4, 0)
        self.create_label(box_frame, "Gender", 4, 1)
        
        # Row 5: Editable Birthdate Field
        self.val_birthdate = self.create_entry_value(box_frame, 5, 0)
        self.gender_var = tk.StringVar()
        self.val_gender = self.create_status_dropdown(
            box_frame, self.gender_var, ["maennlich", "weiblich"], 5, 1
        )

        # Row 6: Status Labels
        self.create_label(box_frame, "is Valid", 6, 0)
        self.create_label(box_frame, "is Paid", 6, 1)
        
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

        # --- Action Buttons (Bottom) ---
        # self.create_action_buttons() # Moved to top




if __name__ == "__main__":
    app = WeighingApp()
    app.mainloop()
