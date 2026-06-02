# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

"""User-global persistent settings for WeighIn.

Lives in ``~/.weighin/settings.json`` (cross-platform via
``os.path.expanduser``). Keeps the launcher (``main.py``) and the GUI
(``gui.py``) in sync on toggles that need to survive a restart.

Currently exposed keys:

- ``weight_scan_enabled`` (bool, default ``True``) — when ``False``, the
  launcher skips spawning the ``weight`` subprocess (scale OCR), so the
  scale camera stays free for other apps. The GUI also enforces this
  at runtime via ``SHUTDOWN`` / ``start_weight_subprocess``.
- ``scanner_mode`` (str, default ``"hotkey"``) — one of
  ``"off" | "hotkey" | "camera"``. Steuert, ob ``real_scanner.py``
  überhaupt läuft und in welchem Modus (USB-Hotkey vs Live-Kamera-OCR).
  Vollständig in ``Libraries/WeighIn.md`` "Subprozess-Lifecycle-Modell"
  dokumentiert.
- ``scanner_camera_index`` (int, default ``0``) — Kamera-Index nur im
  ``"camera"``-Mode wirksam. Default ``0`` weil das auf jedem cam-fähigen
  Mac existiert (interne Camera); Multi-Cam-Setups setzen den Index
  manuell über den ``Kamera auswählen``-Dialog.

Design notes:

- Missing file, malformed JSON, or unreadable path = silent fall-back to
  defaults. The GUI and launcher must keep working without a settings
  file (first-launch users have none).
- Save is best-effort: directory is created if missing, write is atomic
  via ``os.replace`` so a crashed write never leaves a half-file.
- No schema validation beyond defaults — keep keys flat and typed.
"""

import json
import os
import tempfile
from typing import Any, Dict


SETTINGS_DIR_NAME = ".weighin"
SETTINGS_FILE_NAME = "settings.json"

DEFAULTS: Dict[str, Any] = {
    "weight_scan_enabled": True,
    "scanner_mode": "hotkey",  # "off" | "hotkey" | "camera"
    "scanner_camera_index": 0,
}


def settings_path() -> str:
    """Return the absolute path to the settings file (no I/O)."""
    return os.path.join(os.path.expanduser("~"), SETTINGS_DIR_NAME, SETTINGS_FILE_NAME)


def load_settings() -> Dict[str, Any]:
    """Load settings, returning a dict that always contains every default key.

    Missing file / unreadable / malformed JSON → returns ``DEFAULTS.copy()``.
    Existing keys override defaults; unknown keys are preserved.
    """
    result = DEFAULTS.copy()
    path = settings_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return result
    if isinstance(loaded, dict):
        result.update(loaded)
    return result


def save_settings(updates: Dict[str, Any]) -> None:
    """Merge ``updates`` into the persisted settings and write atomically.

    Raises ``OSError`` if the file or directory cannot be written.
    """
    current = load_settings()
    current.update(updates)

    path = settings_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)

    # Atomic write: temp-file in the same directory, then os.replace().
    fd, tmp_path = tempfile.mkstemp(prefix=".settings.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup; re-raise so callers know the save failed.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
