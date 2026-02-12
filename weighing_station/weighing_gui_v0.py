import tkinter as tk
from tkinter import messagebox
import pandas as pd
import os

# Fichier Excel (Hardcodé)
EXCEL_FILE = "teilnehmer_judo_mock.xlsx"

# Pas de JUDO_CLASSES complexe ici, on fait simple pour le proto
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Weighing Station")
        self.geometry("800x600")
        
        # Pas de Theme, tout gris moche
        
        # Layout Frames
        self.left_frame = tk.Frame(self)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        
        self.right_frame = tk.Frame(self)
        self.right_frame.pack(side=tk.RIGHT, expand=True, fill=tk.BOTH, padx=10, pady=10)
        
        # Liste
        tk.Label(self.left_frame, text="Teilnehmer Liste").pack()
        self.listbox = tk.Listbox(self.left_frame, width=30, height=30)
        self.listbox.pack(fill=tk.Y)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        
        # Reload Button
        tk.Button(self.left_frame, text="Reload Excel", command=self.load_data).pack(pady=5)
        
        # Detail View (Moche, tout aligné verticalement)
        tk.Label(self.right_frame, text="DETAILS TEILNEHMER", font=("Arial", 14, "bold")).pack(pady=20)
        
        # Name
        self.lbl_name = tk.Label(self.right_frame, text="Name: ---")
        self.lbl_name.pack(pady=5)
        
        # Club
        self.lbl_club = tk.Label(self.right_frame, text="Verein: ---")
        self.lbl_club.pack(pady=5)
        
        # Geburtsdatum
        self.lbl_birth = tk.Label(self.right_frame, text="Geburt: ---")
        self.lbl_birth.pack(pady=5)
        
        # Gewicht Input
        tk.Label(self.right_frame, text="Gewicht eingeben:").pack(pady=(20, 5))
        self.entry_weight = tk.Entry(self.right_frame)
        self.entry_weight.pack()
        
        # Save Button
        tk.Button(self.right_frame, text="SPEICHERN", command=self.save, bg="lightgreen").pack(pady=20)
        
        # Data storage
        self.participants = []
        self.current_p = None
        self.df = None
        
        self.load_data()

    def load_data(self):
        # Basic load without much error handing
        if os.path.exists(EXCEL_FILE):
            self.df = pd.read_excel(EXCEL_FILE)
            # Remove white spaces from cols
            self.df.columns = self.df.columns.str.strip()
            self.participants = self.df.to_dict('records')
            
            self.listbox.delete(0, tk.END)
            for p in self.participants:
                self.listbox.insert(tk.END, str(p.get('Name', '?')))
        else:
            print("File not found")

    def on_select(self, event):
        sel = self.listbox.curselection()
        if not sel: return
        
        idx = sel[0]
        self.current_p = self.participants[idx]
        
        # Update Labels
        self.lbl_name.config(text=f"Name: {self.current_p.get('Name', '')}")
        self.lbl_club.config(text=f"Verein: {self.current_p.get('Verein', '')}")
        self.lbl_birth.config(text=f"Geburt: {self.current_p.get('Birthdate', '')}")
        
        # Weight
        w = self.current_p.get('Gewicht (kg)', 0)
        self.entry_weight.delete(0, tk.END)
        self.entry_weight.insert(0, str(w))

    def save(self):
        if not self.current_p: return
        
        try:
            w = float(self.entry_weight.get())
            
            # Update Memory
            self.current_p['Gewicht (kg)'] = w
            
            # Update Excel (Very inefficient logic here for prototype)
            p_id = self.current_p.get('ID')
            
            # Find row
            mask = self.df['ID'] == p_id
            self.df.loc[mask, 'Gewicht (kg)'] = w
            
            self.df.to_excel(EXCEL_FILE, index=False)
            messagebox.showinfo("Saved", "Gespeichert!")
            
        except Exception as e:
            messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    app = App()
    app.mainloop()
