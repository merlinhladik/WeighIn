import tkinter as tk
from tkinter import messagebox
import pandas as pd
import json
import os
import random
import asyncio
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

try:
    import websockets
except ImportError:
    websockets = None


JSON_FILE = "data.json"
SETTINGS_FILE = "settings.json"
WS_HOST = "localhost"
WS_PORT = 8765

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
        paid_color = THEME["success"] if self.paid_var.get() == "Zahlung erfolgt" else THEME["error"]
        gender_color = THEME["maennlich"] if self.gender_var.get() == "maennlich" else THEME["weiblich"]

        self.val_valid.config(bg=valid_color)
        self.val_paid.config(bg=paid_color)
        self.val_gender.config(bg=gender_color)

    @staticmethod
    def get_birthdate_text(p: Dict[str, Any]) -> str:
        """Returns a displayable birthdate string from mixed data formats."""
        full_birthdate = p.get("Birthdate") or p.get("Geburtsdatum")
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
        if not os.path.exists(JSON_FILE):
             messagebox.showerror("Error", f"Excel file not found: {JSON_FILE}")
             return

        try:
            with open(JSON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.participants = data if isinstance(data, list) else data.get("participants", [])
            self.update_list(self.participants)
        except Exception as e:
            messagebox.showerror("Error", f"Could not load data: {e}")         

    def load_settings(self):
        """Loads app settings from JSON and applies safe defaults."""
        self.weight_decimal_places = 1
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
        if isinstance(value, int) and value in [1, 2, 3]:
            self.weight_decimal_places = value

        self.weight_tolerance = 0.0
        tol = settings.get("weight_tolerance")
        if isinstance(tol, (int, float)):
            self.weight_tolerance = float(tol)

        self.tolerance_rules = settings.get("tolerance_rules", [])
        if not isinstance(self.tolerance_rules, list):
            self.tolerance_rules = []

    def save_settings(self):
        """Persists app settings to JSON."""

        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "weight_decimal_places": self.weight_decimal_places,
                "weight_tolerance": self.weight_tolerance,
                "tolerance_rules": self.tolerance_rules
            }, f, ensure_ascii=False, indent=2)

    def get_tolerance_for_participant(self, p: Dict) -> Tuple[float, str]:
        """
        Determines the applicable tolerance for a participant based on rules.
        Returns (tolerance_value, rule_name).
        Priority:
        1. First matching Rule (based on Birth Year and Sex)
        2. Global Manual Tolerance (if no rule matches)
        """
        if not p:
            return (self.weight_tolerance, "Global")

        # Extract criteria
        try:
            birth_year = int(p.get("Geburtsjahr")) if p.get("Geburtsjahr") else None
        except (ValueError, TypeError):
            birth_year = None
            
        sex_raw = str(p.get("Geschlecht", "")).lower().strip()
        # Normalize sex: 'm', 'f', or ''
        sex = ""
        if sex_raw.startswith("m"): sex = "m"
        elif sex_raw.startswith("w") or sex_raw.startswith("f"): sex = "f"

        # Check Rules
        for rule in self.tolerance_rules:
            # Rule structure: {"name": str, "sex": "m"/"f"/"all", "min_year": int, "max_year": int, "tol": float}
            r_sex = rule.get("sex", "all")
            r_min = rule.get("min_year")
            r_max = rule.get("max_year")
            
            # 1. Check Sex
            if r_sex != "all" and r_sex != sex:
                continue
            
            # 2. Check Year (if defined)
            if birth_year is not None:
                if r_min is not None and birth_year < r_min:
                    continue
                if r_max is not None and birth_year > r_max:
                    continue
            else:
                # Use rule only if it doesn't restrict years? 
                # Decision: If rule requires year boundaries but user has none, skip rule.
                if r_min is not None or r_max is not None:
                    continue

            # Match found
            return (float(rule.get("tol", 0.0)), rule.get("name", "Rule"))

        # Fallback to global setting
        return (self.weight_tolerance, "Global")

    def format_scale_weight(self, raw_weight: int, participant: Dict = None) -> str:
        """
        Formats integer scale input.
        Returns the NET weight (Raw - Tolerance).
        """
        places = self.weight_decimal_places if self.weight_decimal_places in [1, 2, 3] else 1
        raw_float = raw_weight / (10 ** places)
        
        # Apply Tolerance
        tol, _ = self.get_tolerance_for_participant(participant)
        
        net_weight = raw_float - tol
        if net_weight < 0: net_weight = 0.0
        
        return f"{net_weight:.{places}f}"

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
        
        
        
        

        is_valid = self.to_bool(p.get("Gueltigkeit", p.get("Gueltig", p.get("Valid", False))))
        is_paid = self.to_bool(p.get("Bezahlt", p.get("Paid", False)))
        
        gender_value = str(p.get("Geschlecht") or "").strip().lower()
        is_male = gender_value == "maennlich"

        self.valid_var.set("gueltig" if is_valid else "ungueltig")
        self.paid_var.set("Zahlung erfolgt" if is_paid else "Zahlung offen")
        self.gender_var.set("maennlich" if is_male else "weiblich")
        self.update_status_dropdown_colors()

        weight = 0.0
        self.weight_var.delete(0, tk.END)
        self.weight_var.insert(0, str(weight))
        # self.entry_weight.focus() # Auto-focus for immediate entry

    def save_data(self):
        """Writes current participant data back to JSON."""
        with open(JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(self.participants, f, ensure_ascii=False, indent=2)

    def read_scale(self):
        """Applies pending scale value or simulates one when no external value exists."""
        if self.pending_received_weight is not None:
            formatted_weight = self.format_scale_weight(self.pending_received_weight)
            self.weight_var.delete(0, tk.END)
            self.weight_var.insert(0, formatted_weight)
            self.pending_received_weight = None
            self.close_weight_popup()
            return

        # Get Participant
        participant = None
        sel = self.listbox.curselection()
        if sel:
             if 0 <= sel[0] < len(self.participants):
                 participant = self.participants[sel[0]]

        tol_val, rule_name = self.get_tolerance_for_participant(participant)
        
        simulated_raw = round(random.uniform(20.0, 100.0), 1)
        simulated_net = simulated_raw - tol_val
        if simulated_net < 0: simulated_net = 0.0
        
        self.weight_var.delete(0, tk.END)
        self.weight_var.insert(0, f"{simulated_net:.1f}")
        
        msg = f"Read (Sim): {simulated_raw} kg"
        if tol_val > 0:
            msg += f"\n- {tol_val} kg (Tol: {rule_name})"
            msg += f"\n= {simulated_net:.1f} kg (Net)"
            
        messagebox.showinfo("Scale", msg)

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
        p["Gewicht (kg)"] = weight
        p["Gewicht"] = weight
        p["Vorname"] = first_name
        p["Nachname"] = last_name
        p["Name"] = full_name
        is_valid = self.valid_var.get() == "gueltig"
        is_paid = self.paid_var.get() == "Zahlung erfolgt"
        p["Gueltigkeit"] = is_valid
        p["Gueltig"] = is_valid
        p["Valid"] = is_valid
        p["Bezahlt"] = is_paid
        p["Paid"] = is_paid
        p["Birthdate"] = birthdate
        p["Geburtsdatum"] = birthdate
        parsed_year = self.get_birth_year_from_date(birthdate)
        if parsed_year is not None:
            p["Geburtsjahr"] = parsed_year

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
            "Geburtsdatum": birthdate if birthdate else "",
            "Birthdate": birthdate if birthdate else "",
            "Verein": club if club else None,
            "Gewicht (kg)": 0.0,
            "Gueltigkeit": False,
            "Geschlecht": gender,
            "Bezahlt": False,
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
        popup.geometry("500x600")
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

        # --- Global Fallback Tolerance ---
        tk.Label(popup, text="Global Tolerance (Fallback)", **lbl_style).pack(pady=(15, 5))
        tolerance_var = tk.StringVar(value=str(self.weight_tolerance))
        e_tolerance = tk.Entry(popup, textvariable=tolerance_var, bg=THEME["input_bg"], fg="white", font=("Arial", 11), justify="center")
        e_tolerance.pack(padx=20, pady=5)
        
        # --- Decimal Places ---
        tk.Label(popup, text="Decimal Places", **lbl_style).pack(pady=(10, 5))
        decimal_var = tk.StringVar(value=str(self.weight_decimal_places))
        decimal_dropdown = tk.OptionMenu(popup, decimal_var, "1", "2", "3")
        decimal_dropdown.config(**dropdown_style)
        decimal_dropdown["menu"].config(
            bg=THEME["input_bg"],
            fg=THEME["fg"],
            activebackground=THEME["accent"],
            activeforeground="black",
            font=("Arial", 10),
        )
        decimal_dropdown.pack()

        tk.Frame(popup, height=2, bg=THEME["input_bg"]).pack(fill="x", padx=20, pady=15)

        # --- Rules Section ---
        tk.Label(popup, text="Advanced Tolerance Rules", font=("Arial", 12, "bold"), bg=THEME["bg"], fg=THEME["accent"]).pack(pady=(0, 10))
        
        rules_frame = tk.Frame(popup, bg=THEME["bg"])
        rules_frame.pack(fill="both", expand=True, padx=20)
        
        # Listbox with Scrollbar
        scrollbar = tk.Scrollbar(rules_frame)
        scrollbar.pack(side=tk.RIGHT, fill="y")
        
        self.rules_listbox = tk.Listbox(rules_frame, height=8, bg=THEME["input_bg"], fg="white", font=("Courier", 10), selectbackground=THEME["accent"])
        self.rules_listbox.pack(side=tk.LEFT, fill="both", expand=True)
        self.rules_listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.rules_listbox.yview)
        
        self.update_rules_listbox()

        # Rule Buttons
        btn_frame = tk.Frame(popup, bg=THEME["bg"])
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="+ Add Rule", command=lambda: self.open_add_rule_window(popup), bg=THEME["input_bg"], fg="white").pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="- Delete Selected", command=self.delete_selected_rule, bg=THEME["error"], fg="white").pack(side=tk.LEFT, padx=5)

        tk.Frame(popup, height=2, bg=THEME["input_bg"]).pack(fill="x", padx=20, pady=15)

        # --- Save / Close Buttons ---
        button_frame = tk.Frame(popup, bg=THEME["bg"])
        button_frame.pack(pady=10, side=tk.BOTTOM)

        # Using self.save_settings_from_popup to avoid scope garbage collection
        tk.Button(
            button_frame,
            text="Save Settings",
            command=lambda: self.save_settings_from_popup(popup, decimal_var, tolerance_var),
            bg=THEME["success"],
            fg="black",
            font=("Arial", 10, "bold"),
            width=15,
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

    def update_rules_listbox(self):
        """Refresh the rules listbox content."""
        if hasattr(self, 'rules_listbox') and self.rules_listbox.winfo_exists():
            self.rules_listbox.delete(0, tk.END)
            for r in self.tolerance_rules:
                # Format: "Name [Sex] (Year-Year) -> Tol"
                sex = r.get('sex', 'all').upper()
                ymin = r.get('min_year', '*')
                ymax = r.get('max_year', '*')
                yr_str = f"{ymin}-{ymax}"
                self.rules_listbox.insert(tk.END, f"{r.get('name')} [{sex}] ({yr_str}) -> -{r.get('tol')}kg")

    def delete_selected_rule(self):
        """Deletes the selected rule from the list."""
        sel = self.rules_listbox.curselection()
        if not sel: return
        idx = sel[0]
        del self.tolerance_rules[idx]
        self.update_rules_listbox()

    def open_add_rule_window(self, parent):
        """Popup to add a new rule."""
        win = tk.Toplevel(parent)
        win.title("Add Rule")
        win.geometry("300x400")
        win.configure(bg=THEME["bg"])
        win.transient(parent)
        
        lbl_style = {"bg": THEME["bg"], "fg": THEME["fg"]}
        
        # Name
        tk.Label(win, text="Name (e.g. U18)", **lbl_style).pack(pady=(10,0))
        e_name = tk.Entry(win); e_name.pack()
        
        # Sex
        tk.Label(win, text="Sex", **lbl_style).pack(pady=(10,0))
        sex_var = tk.StringVar(value="all")
        tk.OptionMenu(win, sex_var, "all", "m", "f").pack()
        
        # Years
        tk.Label(win, text="Min Birth Year (empty=any)", **lbl_style).pack(pady=(10,0))
        e_min = tk.Entry(win); e_min.pack()
        
        tk.Label(win, text="Max Birth Year (empty=any)", **lbl_style).pack(pady=(5,0))
        e_max = tk.Entry(win); e_max.pack()
        
        # Tolerance
        tk.Label(win, text="Tolerance (kg)", **lbl_style).pack(pady=(10,0))
        e_tol = tk.Entry(win); e_tol.pack()
        e_tol.insert(0, "0.1")
        
        def add():
            try:
                tol_val = float(e_tol.get().replace(",", "."))
                mn = int(e_min.get()) if e_min.get().strip() else None
                mx = int(e_max.get()) if e_max.get().strip() else None
                
                rule = {
                    "name": e_name.get() or "Rule",
                    "sex": sex_var.get(),
                    "min_year": mn,
                    "max_year": mx,
                    "tol": tol_val
                }
                self.tolerance_rules.append(rule)
                self.update_rules_listbox()
                win.destroy()
            except ValueError:
                messagebox.showerror("Error", "Invalid number format")

        tk.Button(win, text="Add", command=add, bg=THEME["success"]).pack(pady=20)

    def save_settings_from_popup(self, popup, decimal_var, tolerance_var):
        """Helper to save settings from the popup window."""
        try:
            selected_places = int(decimal_var.get())
        except ValueError:
            selected_places = 1

        if selected_places not in [1, 2, 3]:
            selected_places = 1

        try:
            new_tol = float(tolerance_var.get().replace(",", "."))
            if new_tol < 0: new_tol = 0.0
        except ValueError:
            new_tol = 0.0
        
        self.weight_tolerance = new_tol
        self.weight_decimal_places = selected_places
        self.save_settings()

        if self.pending_received_weight is not None and self.weight_popup is not None and self.weight_popup.winfo_exists():
            self.show_weight_popup(self.pending_received_weight)

        popup.destroy()
        msg = f"Settings Saved!\n\nGlobal Tol: {self.weight_tolerance} kg"
        if len(self.tolerance_rules) > 0:
            msg += f"\nRules Active: {len(self.tolerance_rules)}"
        else:
            msg += "\n(No rules)"
            
        messagebox.showinfo("Success", msg)

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
        self.pending_received_weight = weight
        name = self.get_selected_full_name()
        
        # Get Participant for Tolerance Rules
        # self.participants is a list of dicts. We need the selected one.
        # But we only have self.selected_index (int) or logic in update_details.
        # Let's find the participant.
        participant = None
        sel = self.listbox.curselection()
        if sel:
            idx = sel[0]
            if 0 <= idx < len(self.participants):
                participant = self.participants[idx]

        display_weight = self.format_scale_weight(weight, participant)
        
        # Info String regarding tolerance
        tol_info = ""
        # Calculate tolerance used
        tol_val, rule_name = self.get_tolerance_for_participant(participant)
        
        if tol_val > 0:
            places = self.weight_decimal_places
            raw_val = weight / (10 ** places)
            tol_info = f"(Raw: {raw_val:.{places}f} kg | Tol: -{tol_val} kg [{rule_name}])"

        if self.weight_popup is None or not self.weight_popup.winfo_exists():
            popup = tk.Toplevel(self)
            popup.title("Waage")
            popup.geometry("520x350")
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
            name_label.pack(pady=(22, 5))

            # Tolerance Info Label
            self.weight_popup_tol_label = tk.Label(
                popup, 
                text=tol_info,
                bg=THEME["bg"], 
                fg="gray", 
                font=("Arial", 10)
            )
            self.weight_popup_tol_label.pack(pady=(0, 5))

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
                text="Mit 'take current weight' ubernehmen",
                bg=THEME["bg"],
                fg="gray",
                font=("Arial", 10),
            )
            hint_label.pack(pady=(0, 16))

            self.weight_popup = popup
            self.weight_popup_name_label = name_label
            self.weight_popup_value_label = weight_label
            return

        self.weight_popup_name_label.config(text=name)
        self.weight_popup_value_label.config(text=f"{display_weight} kg")
        if self.weight_popup_tol_label:
             self.weight_popup_tol_label.config(text=tol_info)
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
        for client in list(self.ws_clients):
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
            for client in list(self.ws_clients):
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
        #self.weight_var = tk.StringVar()
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
        self.paid_var = tk.StringVar(value="Zahlung offen")
        self.val_valid = self.create_status_dropdown(
            box_frame, self.valid_var, ["gueltig", "ungueltig"], 7, 0
        )
        self.val_paid = self.create_status_dropdown(
            box_frame, self.paid_var, ["Zahlung erfolgt", "Zahlung offen"], 7, 1
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
