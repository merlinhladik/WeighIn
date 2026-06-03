# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

"""Single-instance guard for WeighIn.

WeighIn owns exclusive resources per machine — one camera, one scale, one
``contestants_*.json`` and one WebSocket hub on a fixed port. Running two
instances would fight over all of these, so only one may run at a time.

Mechanism: an exclusive OS file lock on ``~/.weighin/weighin.lock``
(``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows). The kernel releases
the lock automatically when the holding process exits — including on crash or
SIGKILL — so there is no stale-lock problem and nothing to clean up.

Usage::

    from shared.single_instance import acquire_single_instance_lock
    if not acquire_single_instance_lock():
        ...  # another instance is running -> warn + exit

Keep the returned handle for the process lifetime (this module holds it in a
module global), so the lock stays held until the process ends.
"""

import os
import sys
from typing import Optional, TextIO


SETTINGS_DIR_NAME = ".weighin"
LOCK_FILE_NAME = "weighin.lock"

# Module-global so the lock file stays open (and thus locked) for the whole
# process lifetime. Do not let this be garbage-collected.
_lock_handle: Optional[TextIO] = None


def lock_path() -> str:
    """Absolute path to the lock file (no I/O)."""
    return os.path.join(os.path.expanduser("~"), SETTINGS_DIR_NAME, LOCK_FILE_NAME)


def acquire_single_instance_lock() -> bool:
    """Try to acquire the single-instance lock.

    Returns ``True`` if this process is now the sole instance, ``False`` if
    another instance already holds the lock. Idempotent: calling again after a
    successful acquire returns ``True`` without re-locking.
    """
    global _lock_handle
    if _lock_handle is not None:
        return True

    path = lock_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = open(path, "w", encoding="utf-8")
    except OSError:
        # If we cannot even open the lock file, fail open (better to run than to
        # block the operator over a permissions glitch in the home dir).
        return True

    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False

    # Record the PID for diagnostics (purely informational).
    try:
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()) + "\n")
        fh.flush()
    except OSError:
        pass

    _lock_handle = fh
    return True


def warn_already_running(gui: bool = False) -> None:
    """Tell the operator another instance is running. GUI uses a messagebox
    (best-effort), otherwise stderr."""
    msg = ("WeighIn läuft bereits.\n\nEs kann nur eine Instanz gleichzeitig "
           "laufen (eine Kamera, eine Waage, eine Datendatei).")
    if gui:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning("WeighIn", msg)
            root.destroy()
            return
        except Exception:
            pass
    print(msg.replace("\n\n", " "), file=sys.stderr)
