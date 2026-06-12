<!--
SPDX-FileCopyrightText: 2026 TOP Team Combat Control
SPDX-License-Identifier: CC0-1.0
-->

# WeighIn — Build der ausführbaren Variante

Anleitung + Doku zu den beiden Build-Skripten im WSP-Wurzelordner:

- `WSP_Weighin_build.sh` — Linux & macOS
- `WSP_Weighin_build.ps1` — Windows (`.exe`)

## Warum vier Binaries statt einer

WeighIn ist **kein** Ein-Prozess-Programm. Es läuft als **drei** Prozesse
(GUI + Waagen-OCR + QR-Scanner), die über einen Loopback-WebSocket
(`localhost:8766`) reden, plus einen **Launcher**, der die drei startet und
beim Beenden wieder einsammelt:

| Quelle (`sources/`) | Binary        | Rolle                                   |
|---------------------|---------------|-----------------------------------------|
| `main.py`           | `WeighIn`     | Launcher (startet/stoppt die anderen 3) |
| `gui.py`            | `gui`         | Tkinter-GUI, bindet den WS-Server :8766 |
| `weight.py`         | `weight`      | Kamera-OCR der Waagenanzeige            |
| `real_scanner.py`   | `real_scanner`| QR-/Barcode-Scanner                     |

Entscheidend: Der Launcher findet seine Kinder über
`base = os.path.dirname(sys.executable)` und spawnt von dort `gui[.exe]`,
`weight[.exe]`, `real_scanner[.exe]`. **Alle vier Binaries müssen im selben
Ordner liegen.** Genau das produzieren die Skripte.

## Build-Schritte (was die Skripte tun)

1. **venv anlegen** neben dem Repo (`WeighIn/.venv-linux` bzw. `.venv-win`;
   macOS nutzt das bestehende `.venv-macos`).
2. **Abhängigkeiten** aus `WeighIn/requirements.txt` installieren
   (inkl. `pyinstaller`). Die Plattform-Marker in `requirements.txt` ziehen
   automatisch das richtige Kamera-Backend: `pygrabber` (Windows),
   `pyobjc-framework-AVFoundation` (macOS); Linux nutzt V4L über `cv2`.
3. **PyInstaller × 4** — je ein `--onefile`-Build für Launcher und die drei
   Subprozesse, Ausgabe nebeneinander in `dist/<os>/WeighIn/`.
   - Linux/Windows: flache Binaries im Ordner.
   - macOS: `.app`-Bundle; die drei Subprozess-Binaries werden nach
     `WeighIn.app/Contents/MacOS/` gelegt (= `dirname(sys.executable)`).
4. **Plattform-Feinschliff:**
   - **Windows:** `pygrabber` als `--hidden-import` (DirectShow-Kameraliste),
     `AVFoundation` ausgeschlossen.
   - **Linux:** `pygrabber` **und** `AVFoundation` ausgeschlossen.
   - **macOS** (in `WeighIn/scripts/build-macos.sh`): `AVFoundation`
     eingesammelt, `Info.plist` um `NSCameraUsageDescription` etc. ergänzt,
     extended attributes entfernt, ad-hoc-`codesign` — sonst liefert die
     Kamera nur schwarze Frames (TCC-Identität).

## Verwendung

### Linux / macOS

```sh
cd /Users/merlin/Documents/Git/WSP
./WSP_Weighin_build.sh            # setup + build (Default)
./WSP_Weighin_build.sh setup     # nur venv + Abhängigkeiten
./WSP_Weighin_build.sh build     # nur PyInstaller
./WSP_Weighin_build.sh clean     # dist/ + build/ entfernen
```

- **Linux-Ergebnis:** `WeighIn/dist/linux/WeighIn/` mit `WeighIn`, `gui`,
  `weight`, `real_scanner`. Start: `./WeighIn`.
- **macOS-Ergebnis:** `WeighIn/dist/macos/WeighIn.app`. Start:
  `open WeighIn.app` (delegiert an die bewährte `build-macos.sh`-Pipeline).

### Windows

```powershell
cd C:\...\WSP
# einmalig, falls Skripte blockiert sind:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\WSP_Weighin_build.ps1                 # setup + build (Default)
.\WSP_Weighin_build.ps1 -Stage setup    # nur venv
.\WSP_Weighin_build.ps1 -Stage build    # nur PyInstaller
.\WSP_Weighin_build.ps1 -Stage clean
```

- **Ergebnis:** `WeighIn\dist\windows\WeighIn\` mit `WeighIn.exe`, `gui.exe`,
  `weight.exe`, `real_scanner.exe`. Start: `WeighIn.exe`.

## Cross-Compile geht NICHT

PyInstaller bündelt den **lokalen** Python-Interpreter und native Libraries —
es cross-compiliert nicht. Folge: **jede Plattform muss auf ihrer eigenen
Hardware gebaut werden.**

- Die `.exe` lässt sich **nicht** auf dem Mac/Linux erzeugen → auf einem
  Windows-Rechner (oder Windows-VM) `WSP_Weighin_build.ps1` laufen lassen.
- Das Linux-Binary auf einem Linux-Rechner, das `.app` auf dem Mac.

## Voraussetzungen je Plattform

| Plattform | Build-Voraussetzung                          | Laufzeit-Extra |
|-----------|----------------------------------------------|----------------|
| Windows   | Python 3.13 (python.org, inkl. tcl/tk)       | —              |
| macOS     | `brew install python@3.13 python-tk@3.13`    | Kamera-/Accessibility-Freigabe beim 1. Start |
| Linux     | `python3.13`, `python3-tk`                   | `v4l-utils`, `libgl1`; Hotkey-Scanner braucht root |

## Verifiziert

macOS-Build am 2026-06-10 mit `./WSP_Weighin_build.sh build` erzeugt:
`WeighIn.app` (arm64, ad-hoc signiert) mit allen vier Binaries in
`Contents/MacOS/`. Smoke-Test: Launcher startet und spawnt `gui` + `weight` +
`real_scanner` korrekt aus dem Bundle.
