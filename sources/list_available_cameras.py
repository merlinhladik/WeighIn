import sys
import subprocess
from typing import List, Tuple


CameraList = List[Tuple[int, str]]


def list_available_cameras() -> CameraList:
    """
    Returns a list of available cameras.

    Format:
        [(index, name)]

    Windows -> uses pygrabber
    Linux   -> uses v4l2-ctl and filters duplicate video nodes
    macOS   -> uses system_profiler
    """

    if sys.platform.startswith("win"):
        return _list_windows_cameras()

    if sys.platform.startswith("linux"):
        return _list_linux_cameras()

    if sys.platform == "darwin":
        return _list_macos_cameras()

    return []


# -----------------------------
# Windows
# -----------------------------

def _list_windows_cameras() -> CameraList:
    from pygrabber.dshow_graph import FilterGraph
    try:
        graph = FilterGraph()
        names = graph.get_input_devices()
        return [(i, str(name)) for i, name in enumerate(names)]
    except Exception:
        return []


# -----------------------------
# Linux
# -----------------------------

def _list_linux_cameras() -> CameraList:
    """
    Uses v4l2-ctl to list cameras and removes duplicate video nodes.
    """

    try:
        result = subprocess.run(
            ["v4l2-ctl", "--list-devices"],
            capture_output=True,
            text=True,
            check=True,
        )

        lines = result.stdout.splitlines()

        cameras = []
        index = 0
        current_name = None

        for line in lines:
            if not line.startswith("\t") and line.strip():
                current_name = line.strip()

            elif line.startswith("\t") and current_name:
                dev = line.strip()

                if dev.startswith("/dev/video"):
                    cameras.append((index, current_name))
                    index += 1
                    current_name = None

        return cameras

    except Exception:
        return []


# -----------------------------
# macOS
# -----------------------------

def _list_macos_cameras() -> CameraList:
    try:
        result = subprocess.run(
            ["system_profiler", "SPCameraDataType"],
            capture_output=True,
            text=True,
            check=True,
        )

        cameras = []
        index = 0

        for line in result.stdout.splitlines():
            line = line.strip()

            if line.endswith(":") and "camera" in line.lower():
                name = line.replace(":", "")
                cameras.append((index, name))
                index += 1

        return cameras

    except Exception:
        return []