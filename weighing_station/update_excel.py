import pandas as pd
import random
import os

file_path = "teilnehmer_judo_mock.xlsx"

if not os.path.exists(file_path):
    print(f"Error: {file_path} not found.")
    exit(1)

df = pd.read_excel(file_path)

# Add Gender if missing
if 'Gender' not in df.columns and 'Geschlecht' not in df.columns:
    df['Gender'] = [random.choice(['M', 'F']) for _ in range(len(df))]
    print("Added 'Gender' column.")

# Add Birthdate if missing
if 'Birthdate' not in df.columns and 'Geburtsdatum' not in df.columns:
    # Generate fake birthdates based on Age if available, else random
    birthdates = []
    current_year = 2026
    for age in df.get('Alter', [20]*len(df)):
        try:
            year = current_year - int(age)
        except:
            year = 2000
        day = random.randint(1, 28)
        month = random.randint(1, 12)
        birthdates.append(f"{day:02d}.{month:02d}.{year}")
    df['Birthdate'] = birthdates
    print("Added 'Birthdate' column.")

# Add Paid if missing or update
# Force some False values for testing
df['Paid'] = [random.choice([True, False, True]) for _ in range(len(df))]
print("Updated 'Paid' column with mixed values.")

# Add Valid if missing or update
# Force some False values for testing
df['Valid'] = [random.choice([True, True, False]) for _ in range(len(df))]
print("Updated 'Valid' column with mixed values.")

df.to_excel(file_path, index=False)
print(f"Updated {file_path} with new columns.")
