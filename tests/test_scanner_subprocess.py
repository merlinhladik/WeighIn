# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the GUI-owned scanner-subprocess lifecycle.

Spiegel zu `test_weight_subprocess.py`. Covers the runtime mode-switch
path for `real_scanner.py` (off/hotkey/camera) — the launcher
`main.py` reads settings at boot, but the GUI itself spawns or kills
the subprocess on settings change.

Tests instantiate no `WeighingApp`; methods are called unbound against
a `SimpleNamespace` mock for `self`.
"""

import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from gui import WeighingApp


# ---------------------------------------------------------------------------
# _scanner_subprocess_argv
# ---------------------------------------------------------------------------

def test_scanner_argv_dev_mode(monkeypatch):
    """Dev-Modus -> [python, .../sources/real_scanner.py]."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    argv = WeighingApp._scanner_subprocess_argv(SimpleNamespace())
    assert argv is not None
    assert argv[0] == sys.executable
    assert argv[1].endswith(os.path.join("sources", "real_scanner.py"))
    assert os.path.isfile(argv[1])


def test_scanner_argv_packaged_with_existing_binary(monkeypatch, tmp_path):
    fake_exe = tmp_path / "gui"
    fake_exe.write_text("#!fake")
    fake_scanner = tmp_path / ("real_scanner.exe" if os.name == "nt" else "real_scanner")
    fake_scanner.write_text("#!fake")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    argv = WeighingApp._scanner_subprocess_argv(SimpleNamespace())
    assert argv == [str(fake_scanner)]


def test_scanner_argv_packaged_missing_binary_returns_none(monkeypatch, tmp_path):
    fake_exe = tmp_path / "gui"
    fake_exe.write_text("#!fake")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    argv = WeighingApp._scanner_subprocess_argv(SimpleNamespace())
    assert argv is None


# ---------------------------------------------------------------------------
# _stop_scanner_subprocess
# ---------------------------------------------------------------------------

def test_stop_managed_is_noop_when_scanner_subprocess_is_none():
    """_stop_scanner_subprocess delegiert an _stop_managed_subprocess."""
    app = SimpleNamespace(scanner_subprocess=None)
    WeighingApp._stop_managed_subprocess(app, "scanner_subprocess")
    assert app.scanner_subprocess is None


def test_stop_managed_is_noop_when_scanner_subprocess_already_exited():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=2.0)
    assert proc.poll() is not None
    app = SimpleNamespace(scanner_subprocess=proc)
    WeighingApp._stop_managed_subprocess(app, "scanner_subprocess")
    assert app.scanner_subprocess is None


@pytest.mark.skipif(os.name == "nt", reason="setsid/killpg sind POSIX-only")
def test_stop_managed_terminates_running_scanner_subprocess():
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        preexec_fn=os.setsid,
    )
    time.sleep(0.1)
    assert proc.poll() is None

    app = SimpleNamespace(scanner_subprocess=proc)
    WeighingApp._stop_managed_subprocess(app, "scanner_subprocess")

    assert app.scanner_subprocess is None
    proc.wait(timeout=2.0)
    assert proc.returncode is not None


# ---------------------------------------------------------------------------
# start_scanner_subprocess — no-spawn-Pfade
# ---------------------------------------------------------------------------

def test_start_scanner_returns_true_if_already_running():
    """Wenn scanner_subprocess.poll() is None -> kein Re-Spawn."""
    fake_running = SimpleNamespace(poll=lambda: None)
    app = SimpleNamespace(scanner_subprocess=fake_running)
    assert WeighingApp.start_scanner_subprocess(app, "camera", 2) is True
    assert app.scanner_subprocess is fake_running


def test_start_scanner_returns_false_when_argv_unresolvable():
    """argv-Resolver liefert None -> Start ohne Crash, False zurück."""
    app = SimpleNamespace(
        scanner_subprocess=None,
        _scanner_subprocess_argv=lambda: None,
    )
    assert WeighingApp.start_scanner_subprocess(app, "camera", 1) is False
    assert app.scanner_subprocess is None
