# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plattformabhängiges Öffnen von OpenCV-Kameras.

Hintergrund (Windows): OpenCV nutzt standardmäßig das MSMF-Backend (Media
Foundation). Auf vielen Webcams öffnet MSMF entweder gar nicht, hängt ~30 s
beim Öffnen einer belegten/unverfügbaren Kamera oder liefert anschließend
keine Frames (``OnReadSample ... error status: -1072875772``) — die GUI zeigt
dann kein Live-Bild. DirectShow (``CAP_DSHOW``) öffnet funktionierende Kameras
schneller, scheitert bei nicht nutzbaren Kameras sofort (statt 30 s zu hängen)
und verwendet dieselbe Geräte-Indizierung wie ``pygrabber`` (das die
Kamera-Liste in ``list_available_cameras`` erzeugt). Deshalb erzwingen wir auf
Windows DirectShow.

macOS (AVFoundation) und Linux (V4L2) funktionieren mit dem Default-Backend;
dort wird nichts erzwungen.
"""

import sys

import cv2


def open_capture(index: int) -> "cv2.VideoCapture":
    """Öffnet ``cv2.VideoCapture`` mit dem für das OS passenden Backend."""
    if sys.platform.startswith("win"):
        return cv2.VideoCapture(index, cv2.CAP_DSHOW)
    return cv2.VideoCapture(index)
