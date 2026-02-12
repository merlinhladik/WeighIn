"""
Judo Weighing Station GUI
=========================

This module implements the main graphical user interface for the Judo Weighing Station.
It allows operators to:
- Search and select pre-registered participants from an Excel list.
- View participant details (Name, Club, Age, Gender).
- Input weight (simulated scale reading or manual entry).
- Automatically calculate the correct weight class based on Age and Gender.
- Add new participants on-the-fly (Late Entries).
- Save updated data back to the Excel source.

Dependencies:
- tkinter: For the GUI.
- pandas: For Excel file handling.
- openpyxl: Required by pandas for .xlsx files.
"""

import tkinter as tk
from tkinter import messagebox
import pandas as pd
import os
import random
from datetime import datetime
from typing import Dict, List, Optional, Any
from network_manager import NetworkManager
from camera_manager import CameraManager

# --- Configuration Constants ---
EXCEL_FILE = "teilnehmer_judo_mock.xlsx"

# Theme Configuration (Dark Mode)
THEME = {
    "bg": "#121212",        # Background: Very dark grey
    "fg": "#FFFFFF",        # Foreground: White text
    "accent": "#BB86FC",    # Accent: Purple
    "secondary": "#2C2C2C", # Secondary: Lighter grey for panels/frames
    "input_bg": "#333333",  # Input Fields: Dark Grey
    "input_fg": "#FFFFFF",  # Input Text: White
    "success": "#03DAC6",   # Success State: Teal
    "error": "#CF6679"      # Error State: Red
}

# --- Judo Rules Configuration ---
# Dictionary defining weight classes per Age Group and Gender.
# Keys: Age Group (U11, U13, U15, U18, Seniors)
# Sub-keys: "M" (Male), "F" (Female)
# Values: List of upper weight limits. 999 represents the open category (+).
# Note: These values are approximations based on DJB/IJF rules and may vary locally.
JUDO_CLASSES = {
    "U11": {
        "M": [-23, -26, -29, -32, -35, -38, -42, -46, 999], 
        "F": [-22, -25, -28, -31, -34, -38, -42, -46, 999]
    },
    "U13": {
        "M": [-29, -32, -35, -38, -42, -46, -50, -55, 999],
        "F": [-28, -31, -34, -38, -42, -46, -50, -55, 999]
    },
    "U15": {
        "M": [-34, -37, -40, -43, -46, -50, -55, -60, -66, 999],
        "F": [-33, -36, -40, -44, -48, -52, -57, -63, 999]
    },
    "U18": {
        "M": [-43, -46, -50, -55, -60, -66, -73, -81, -90, 999],
        "F": [-40, -44, -48, -52, -57, -63, -70, -78, 999]
    },
    "Aktive": {
        "M": [-60, -66, -73, -81, -90, -100, 999],
        "F": [-48, -52, -57, -63, -70, -78, 999]
    }
}


class WeighingApp(tk.Tk):
    """
    Main Application Class for the Weighing Station.
    Inherits from tk.Tk.
    """

    def __init__(self):
        super().__init__()
        self.title("Judo Weighing Station")
        self.geometry("1100x700")
        self.configure(bg=THEME["bg"])
        
        # Data Storage
        self.participants: List[Dict[str, Any]] = []
        self.selected_participant: Optional[Dict[str, Any]] = None
        self.df: Optional[pd.DataFrame] = None

        # Initialization
        self.network = NetworkManager(self.on_network_message)
        self.network.start_connection()
        
        # Initialize Camera Manager (not started yet)
        self.camera = CameraManager(self.on_qr_scanned)

        
        self.create_layout()
        self.load_data()

    def on_network_message(self, msg):
        """Callback for messages coming FROM backend."""
        print(f"GUI received: {msg}")
        # Here we could update UI based on backend events

    def on_qr_scanned(self, data: str):
        """
        Callback triggered when the camera detects a QR code.
        """
        # Thread-Safety: UI updates must run in the main thread
        self.after(0, lambda: self.process_qr_data(data))

    def process_qr_data(self, data: str):
        """
        Processes the QR data in the main thread.
        """
        print(f"[GUI] QR Scanned: {data}")
        self.camera.stop_camera() # Close camera when someone is found
        
        # Try to find the participant by ID
        # Assumption: QR code contains the ID directly (e.g. "1042")
        found_p = None
        
        # 1. Direct ID Match
        for p in self.participants:
            if str(p.get('ID')) == data.strip():
                found_p = p
                break
        
        if found_p:
            # Participant found! Start weighing simulation
            # TODO: Later read real weight here
            messagebox.showinfo("QR Scan", f"Participant found: {found_p.get('Name')}")
            
            # Select the participant
            self.selected_participant = found_p
            self.show_details(found_p)
            
            # Simulate weight measurement and show Focus View
            # (Similar to simulate_qr_scan, but now with real trigger)
            mock_weight = round(random.uniform(30.0, 100.0), 1)
            self.show_focus_view(found_p, mock_weight)
            
        else:
            messagebox.showwarning("QR Scan", f"No participant found with ID '{data}'.")


    def create_layout(self):
        """Constructs the visual layout of the application."""
        
        # --- Sidebar (Left Panel) ---
        sidebar = tk.Frame(self, bg=THEME["secondary"], width=300)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False) # Prevent shrinking

        # Sidebar Title
        tk.Label(sidebar, text="Searchbar for\npresigned", bg=THEME["secondary"], fg=THEME["fg"], 
                 font=("Arial", 14, "bold"), justify="center").pack(pady=(20, 5))

        # Network Status Indicator
        self.lbl_status = tk.Label(sidebar, text="● Connecting...", bg=THEME["secondary"], fg="orange", font=("Arial", 10))
        self.lbl_status.pack(pady=(0, 15))
        
        # Periodic check for connection status
        self.after(1000, self.check_connection_status)

        # Search Input
        self.search_var = tk.StringVar()
        self.search_var.trace("w", self.filter_list) # Bind text change to filter function
        search_entry = tk.Entry(sidebar, textvariable=self.search_var, bg=THEME["input_bg"], 
                                fg=THEME["input_fg"], insertbackground="white", font=("Arial", 12))
        search_entry.pack(fill=tk.X, padx=20, pady=(0, 20))
        
        # Listbox Header
        tk.Label(sidebar, text="some pre signed\npeople", bg=THEME["secondary"], fg="gray", 
                 font=("Arial", 12), justify="center").pack(pady=(10, 5))

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
        self.create_label(box_frame, "Age", 2, 1)

        # Row 3: Weight Entry and Age Display
        self.weight_var = tk.StringVar()
        self.weight_var.trace("w", self.update_category_label) # Real-time category calculation
        self.entry_weight = tk.Entry(box_frame, textvariable=self.weight_var, bg=THEME["input_bg"], 
                                     fg=THEME["accent"], font=("Arial", 20, "bold"), justify="center", width=10)
        self.entry_weight.grid(row=3, column=0, padx=20, pady=5)
        
        self.val_age = self.create_value(box_frame, "---", 3, 1)

        # Row 4: Calculated Category Display
        self.lbl_category = tk.Label(box_frame, text="---", bg=THEME["bg"], fg=THEME["accent"], font=("Arial", 12, "italic"))
        self.lbl_category.grid(row=4, column=0, sticky="n", pady=0)

        # Row 5: Club and Gender Labels
        self.create_label(box_frame, "Club", 5, 0)
        self.create_label(box_frame, "Gender", 5, 1)

        # Row 6: Club and Gender Values
        self.val_club = self.create_value(box_frame, "---", 6, 0)
        self.val_gender = self.create_value(box_frame, "---", 6, 1)

        # Row 7: Birthdate Label
        self.create_label(box_frame, "Birthdate", 7, 0)
        
        # Row 8: Editable Birthdate Field
        self.val_birthdate = self.create_entry_value(box_frame, 8, 0)

        # Row 9: Status Labels
        self.create_label(box_frame, "Valid ?", 9, 0)
        self.create_label(box_frame, "Paid ?", 9, 1)
        
        # Row 10: Status Values (Color-coded)
        # Adding extra bottom padding to prevent sticking to the box border
        self.val_valid = self.create_value(box_frame, "---", 10, 0, pady=(5, 40))
        self.val_paid = self.create_value(box_frame, "---", 10, 1, pady=(5, 40))

        # --- Action Buttons (Bottom) ---
        # self.create_action_buttons() # Moved to top

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
        
        # Button 1: Close System (Exit)
        tk.Button(btn_container, text="Close the system", command=self.destroy, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Button 2: Add New Participant (Manual Entry)
        tk.Button(btn_container, text="new pre signed entry", command=self.open_add_participant_window, width=20, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Button 3: Save Weight (Update Participant)
        tk.Button(btn_container, text="new weight for\ncurrent person", command=self.save_weight, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Button 4: Reset Weight Input
        tk.Button(btn_container, text="reset weight for\ncurrent person", command=self.reset_weight, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Button 5: Read from Scale (Mock Simulation)
        tk.Button(btn_container, text="take current weight", command=self.read_scale, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Button 6: Simulate QR Scan (Focus View)
        tk.Button(btn_container, text="Simulate QR Scan", command=self.simulate_qr_scan, width=18, bg=THEME["accent"], fg="black", font=("Arial", 10, "bold"), bd=1, relief="flat", height=2).pack(side=tk.LEFT, padx=5)

    # --- UI Helper Methods ---
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

    # --- Data Handling Methods ---
    def load_data(self):
        """Loads participant data from the Excel file."""
        if not os.path.exists(EXCEL_FILE):
             messagebox.showerror("Error", f"Excel file not found: {EXCEL_FILE}")
             return

        try:
            self.df = pd.read_excel(EXCEL_FILE)
            self.df.columns = self.df.columns.str.strip() # Sanitize columns
            self.participants = self.df.to_dict('records')
            self.update_list(self.participants)
        except Exception as e:
            messagebox.showerror("Error", f"Could not load data: {e}")

    def update_list(self, data: List[Dict]):
        """Refreshes the sidebar listbox with the provided data."""
        self.listbox.delete(0, tk.END)
        for p in data:
            name = p.get('Name', 'Unknown')
            p_id = p.get('ID', '?')
            self.listbox.insert(tk.END, f"{name} ({p_id})")

    def filter_list(self, *args):
        """Filters the participant list based on the search bar input."""
        query = self.search_var.get().lower()
        if not query:
            self.update_list(self.participants)
            return
        
        filtered = [p for p in self.participants if query in str(p.get('Name', '')).lower()]
        self.update_list(filtered)

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
        self.val_birthdate.insert(0, str(p.get('Birthdate', p.get('Geburtsdatum', '---'))))

        # Update Read-Only Fields
        self.val_club.config(text=p.get('Verein', '---'))
        self.val_gender.config(text=str(p.get('Gender', p.get('Geschlecht', '---'))))
        self.val_age.config(text=str(p.get('Alter', '---')))

        # Visual Feedback for Status (Valid/Paid)
        is_valid = str(p.get('Valid', p.get('Gueltig', False))).lower() in ['true', '1', 'yes']
        is_paid = str(p.get('Paid', p.get('Bezahlt', False))).lower() in ['true', '1', 'yes']

        self.val_valid.config(text="YES" if is_valid else "NO", fg=THEME["success"] if is_valid else THEME["error"])
        self.val_paid.config(text="YES" if is_paid else "NO", fg=THEME["success"] if is_paid else THEME["error"])

        # Update Weight
        weight = p.get('Gewicht (kg)', 0)
        self.weight_var.set(str(weight))
        self.entry_weight.focus() # Auto-focus for immediate entry

    # --- Logic Helpers ---
    def get_age_group(self, age: str) -> str:
        """Determines the Judo age category based on age."""
        try:
            val = int(age)
            if val <= 10: return "U11"
            if val <= 12: return "U13"
            if val <= 14: return "U15"
            if val <= 17: return "U18"
            return "Aktive"
        except (ValueError, TypeError):
            return "Aktive" # Default safe fallback

    def get_weight_class(self, group: str, gender: str, weight: float) -> str:
        """Calculates the weight class based on Category, Gender, and Weight."""
        g = str(gender).upper().strip()
        if g not in ["M", "F"]: 
            return "?"
        
        # Retrieve class limits for the group/gender
        classes = JUDO_CLASSES.get(group, {}).get(g, [])
        
        for limit in classes:
            # Limits are typically negative (e.g. -66), abs() handles this.
            # 999 is used as specific marker for open weight (+).
            if weight <= abs(limit):
                return f"{limit} kg" if limit < 900 else f"+{classes[-2]} kg"
        return "Unknown"

    def update_category_label(self, *args):
        """Callback to update the Category Label in real-time."""
        try:
            w = float(self.weight_var.get())
        except ValueError:
            self.lbl_category.config(text="Invalid Weight", fg=THEME["error"])
            return

        age_txt = self.val_age.cget("text")
        gender_txt = self.val_gender.cget("text")
        
        group = self.get_age_group(age_txt)
        cat = self.get_weight_class(group, gender_txt, w)

        self.lbl_category.config(text=f"{group} {cat}", fg=THEME["success"])

    # --- Action Methods ---
    def reset_weight(self):
        """Resets the weight input to 0."""
        self.weight_var.set("0.0")
        self.entry_weight.focus()

    def read_scale(self):
        """Simulates reading from a digital scale."""
        # TODO: Replace this with actual serial port reading logic
        simulated_weight = round(random.uniform(20.0, 100.0), 1)
        self.weight_var.set(str(simulated_weight))
        messagebox.showinfo("Scale", f"Read from scale: {simulated_weight} kg")

    def save_weight(self):
        """
        Saves changes (Weight, Name, Birthdate) to Memory and Excel.
        Sends the weight via WebSocket to the backend.
        """
        if not self.selected_participant:
            return
        
        try:
            # 1. Capture Input
            new_weight = float(self.weight_var.get())
            new_prename = self.val_prename.get().strip()
            new_surname = self.val_surname.get().strip()
            new_birthdate = self.val_birthdate.get().strip()
            
            new_full_name = f"{new_prename} {new_surname}"
            
            # 2. Update InMemory Dict
            p = self.selected_participant
            p['Gewicht (kg)'] = new_weight
            p['Name'] = new_full_name
            p['Vorname'] = new_prename
            # Update appropriate birthdate key
            if 'Birthdate' in p: p['Birthdate'] = new_birthdate
            if 'Geburtsdatum' in p: p['Geburtsdatum'] = new_birthdate
            
            # 3. Update DataFrame (Excel Mirror)
            p_id = str(p.get('ID'))
            self.df['ID'] = self.df['ID'].astype(str) # Ensure string match
            mask = self.df['ID'] == p_id
            
            if not mask.any():
                 messagebox.showerror("Error", "Participant ID not found in file.")
                 return

            self.df.loc[mask, 'Gewicht (kg)'] = new_weight
            self.df.loc[mask, 'Name'] = new_full_name
            self.df.loc[mask, 'Vorname'] = new_prename
            
            if 'Birthdate' in self.df.columns: self.df.loc[mask, 'Birthdate'] = new_birthdate
            elif 'Geburtsdatum' in self.df.columns: self.df.loc[mask, 'Geburtsdatum'] = new_birthdate
            
            # 4. Write to File
            self.df.to_excel(EXCEL_FILE, index=False)
            
            # 5. Send to Backend (WebSocket)
            sent = self.network.send_weight(p_id, new_weight)
            status_msg = "Saved locally" + (" & to Backend 📡" if sent else " (Local only)")
            
            messagebox.showinfo("Success", f"{status_msg}\nUpdated {new_full_name}\nWeight: {new_weight} kg")
            
            # 6. Refresh List
            self.update_list(self.participants)
            
        except ValueError:
            messagebox.showerror("Error", "Invalid weight format. Please enter a number.")
        except Exception as e:
            messagebox.showerror("Error", f"Save failed: {e}")

    # --- New Participant Feature ---
    def open_add_participant_window(self):
        """Opens a popup window to add a new participant manually."""
        popup = tk.Toplevel(self)
        popup.title("Add New Participant")
        popup.geometry("400x500")
        popup.configure(bg=THEME["bg"])
        
        # Helper for styling
        lbl_style = {"bg": THEME["bg"], "fg": THEME["fg"], "font": ("Arial", 11)}
        entry_style = {"bg": THEME["input_bg"], "fg": "white", "font": ("Arial", 11), "insertbackground": "white"}
        
        # Form Fields
        tk.Label(popup, text="First Name:", **lbl_style).pack(pady=(20, 5))
        e_first = tk.Entry(popup, **entry_style)
        e_first.pack(fill=tk.X, padx=20, pady=5)
        
        tk.Label(popup, text="Last Name:", **lbl_style).pack(pady=(10, 5))
        e_last = tk.Entry(popup, **entry_style)
        e_last.pack(fill=tk.X, padx=20, pady=5)
        
        tk.Label(popup, text="Birthdate (DD.MM.YYYY):", **lbl_style).pack(pady=(10, 5))
        e_birth = tk.Entry(popup, **entry_style)
        e_birth.pack(fill=tk.X, padx=20, pady=5)
        
        tk.Label(popup, text="Club:", **lbl_style).pack(pady=(10, 5))
        e_club = tk.Entry(popup, **entry_style)
        e_club.pack(fill=tk.X, padx=20, pady=5)
        
        # Radio Buttons for Gender
        tk.Label(popup, text="Gender:", **lbl_style).pack(pady=(10, 5))
        gender_var = tk.StringVar(value="M")
        g_frame = tk.Frame(popup, bg=THEME["bg"])
        g_frame.pack()
        tk.Radiobutton(g_frame, text="Male", variable=gender_var, value="M", 
                       bg=THEME["bg"], fg=THEME["fg"], selectcolor=THEME["secondary"]).pack(side=tk.LEFT, padx=10)
        tk.Radiobutton(g_frame, text="Female", variable=gender_var, value="F", 
                       bg=THEME["bg"], fg=THEME["fg"], selectcolor=THEME["secondary"]).pack(side=tk.LEFT, padx=10)
        
        # Popup Buttons
        btn_frame = tk.Frame(popup, bg=THEME["bg"])
        btn_frame.pack(pady=30)
        
        tk.Button(btn_frame, text="SAVE", 
                  command=lambda: self.save_new_participant(popup, e_first, e_last, e_birth, e_club, gender_var),
                  bg=THEME["success"], fg="black", font=("Arial", 10, "bold"), width=15).pack(side=tk.LEFT, padx=10)
                  
        tk.Button(btn_frame, text="CANCEL", command=popup.destroy,
                  bg=THEME["error"], fg="white", font=("Arial", 10, "bold"), width=15).pack(side=tk.LEFT, padx=10)

    def save_new_participant(self, popup, e_first, e_last, e_birth, e_club, gender_var):
        """Validates input and saves the new participant."""
        first = e_first.get().strip()
        last = e_last.get().strip()
        birth = e_birth.get().strip()
        club = e_club.get().strip()
        gender = gender_var.get()
        
        if not first or not last:
            messagebox.showwarning("Missing Info", "Name is required!", parent=popup)
            return
            
        # ID Generation (Simple Auto-Increment)
        try:
            ids = [int(p['ID']) for p in self.participants if str(p.get('ID', '')).isdigit()]
            new_id = max(ids) + 1 if ids else 1000
        except ValueError:
            new_id = 1000
            
        full_name = f"{first} {last}"
        
        # Create Data Record
        # Note: Using both English/German keys to ensure compatibility with different Excel structures
        new_p = {
            "ID": new_id,
            "Name": full_name,
            "Vorname": first,
            "Verein": club,
            "Gender": gender,
            "Geschlecht": gender,
            "Birthdate": birth,
            "Geburtsdatum": birth,
            "Gewicht (kg)": 0.0,
            "Alter": self.calculate_age_manual(birth),
            "Valid": True,  # Assume valid for manual entry
            "Paid": True    # Assume paid for manual entry (or handle separately)
        }
        
        # Memory Update
        self.participants.append(new_p)
        
        # Excel Update
        new_row = pd.DataFrame([new_p])
        self.df = pd.concat([self.df, new_row], ignore_index=True)
        try:
             self.df.to_excel(EXCEL_FILE, index=False)
        except Exception as e:
             messagebox.showerror("Error", f"Save failed: {e}", parent=popup)
             return
             
        self.update_list(self.participants)
        popup.destroy()
        messagebox.showinfo("Success", f"Added Participant:\n{full_name}")

    def calculate_age_manual(self, birthdate_str: str) -> int:
        """Calculates age from birthdate string (DD.MM.YYYY)."""
        try:
            parts = birthdate_str.split('.')
            if len(parts) == 3:
                birth_year = int(parts[2])
                current_year = datetime.now().year
                return current_year - birth_year
        except (ValueError, IndexError):
            pass
        return 0 # Default if parse fail

    # --- Focus View (Post-Scan) ---
    def simulate_qr_scan(self):
        """Simulates a QR scan event + Scale stabilization to trigger Focus View."""
        if not self.participants:
            messagebox.showinfo("Info", "No participants loaded.")
            return

        # 1. Simulate finding a participant via QR
        # In a real scenario, this would come from the QR string parser
        p = random.choice(self.participants)
        
        # 2. Simulate getting a stable weight
        weight = round(random.uniform(30.0, 100.0), 1)
        
        # 3. Trigger the Focus View
        self.show_focus_view(p, weight)

    def start_camera_scan(self):
        """Starts the camera scanning mode."""
        self.camera.start_camera()


    def show_focus_view(self, participant: Dict, weight: float):
        """
        Displays a full-screen, simplified view for quick confirmation.
        Shows: PreName, SurName, Measured Weight.
        """
        # Create a new top-level window
        top = tk.Toplevel(self)
        top.title("Weighing Confirmation")
        top.attributes("-fullscreen", True) # Full screen mode
        top.configure(bg="black")
        
        # Exit shortcut (Escape key)
        top.bind("<Escape>", lambda e: top.destroy())

        # Layout Container (Centered)
        container = tk.Frame(top, bg="black")
        container.place(relx=0.5, rely=0.5, anchor="center")

        # Name Display (Huge Font)
        full_name = participant.get('Name', 'Unknown Name')
        parts = full_name.split()
        pre = parts[0] if parts else ""
        sur = " ".join(parts[1:]) if len(parts) > 1 else ""

        tk.Label(container, text="Participant Identified", fg="gray", bg="black", font=("Arial", 20)).pack(pady=(0, 50))

        name_frame = tk.Frame(container, bg="black")
        name_frame.pack(pady=20)
        
        # PreName
        tk.Label(name_frame, text=pre, fg="white", bg="black", font=("Arial", 60, "bold")).pack(side=tk.LEFT, padx=30)
        # SurName
        tk.Label(name_frame, text=sur, fg="white", bg="black", font=("Arial", 60, "bold")).pack(side=tk.LEFT, padx=30)

        # Weight Display (Huge & Green)
        tk.Label(container, text=f"{weight} kg", fg="#00FF00", bg="black", font=("Arial", 120, "bold")).pack(pady=50)

        # Instructions
        tk.Label(container, text="Press [ENTER] to Confirm & Save   |   Press [ESC] to Cancel", 
                 fg="gray", bg="black", font=("Arial", 16)).pack(pady=50)

        # Auto-Confirm Logic or Key Bindings
        def confirm_action(event=None):
            # Update the main app with this data
            self.selected_participant = participant
            self.show_details(participant) # Update UI
            self.weight_var.set(str(weight)) # Set weight
            self.save_weight() # Save it
            top.destroy()

        top.bind("<Return>", confirm_action)
        top.focus_force()

    def create_action_buttons(self):
        """Creates the bottom navigation and action buttons."""
        # Use main_container if available, else fallback to self (for safety)
        parent = getattr(self, 'main_container', self)
        
        btn_container = tk.Frame(parent, bg=THEME["bg"])
        
        if hasattr(self, 'main_container'):
             # Pack at the bottom of the right panel
            btn_container.pack(side=tk.BOTTOM, fill=tk.X, pady=(20, 30))
        else:
            # Fallback (should not happen if create_layout runs first)
            btn_container.place(relx=0.5, rely=0.95, anchor="s")

        btn_opts = {
            "bg": THEME["input_bg"], "fg": "white", 
            "font": ("Arial", 10, "bold"), "bd": 1, 
            "relief": "flat", "height": 2
        }
        
        # Button 1: Close System (Exit)
        tk.Button(btn_container, text="Close the system", command=self.destroy, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Button 2: Add New Participant (Manual Entry)
        tk.Button(btn_container, text="new pre signed entry", command=self.open_add_participant_window, width=20, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Button 3: Save Weight (Update Participant)
        tk.Button(btn_container, text="new weight for\ncurrent person", command=self.save_weight, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Button 4: Reset Weight Input
        tk.Button(btn_container, text="reset weight for\ncurrent person", command=self.reset_weight, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Button 5: Read from Scale (Mock Simulation)
        tk.Button(btn_container, text="take current weight", command=self.read_scale, width=18, **btn_opts).pack(side=tk.LEFT, padx=5)

        # Button 6: Simulate QR Scan (Focus View)
        # Button 6: Start Camera (Real Implementation)
        tk.Button(btn_container, text="Start Camera 📷", command=self.start_camera_scan, width=18, bg=THEME["accent"], fg="black", font=("Arial", 10, "bold"), bd=1, relief="flat", height=2).pack(side=tk.LEFT, padx=5)

    # --- Network Helpers ---
    def check_connection_status(self):
        """Updates the visual status indicator."""
        if self.network.connected:
            self.lbl_status.config(text="● ONLINE (WebSocket)", fg=THEME["success"])
        else:
            self.lbl_status.config(text="● OFFLINE", fg=THEME["error"])
        self.after(2000, self.check_connection_status)

    def destroy(self):
        """Cleanup on exit."""
        if hasattr(self, 'network'):
            self.network.stop_connection()
        if hasattr(self, 'camera'):
            self.camera.stop_camera()

        super().destroy()


if __name__ == "__main__":
    app = WeighingApp()
    app.mainloop()
