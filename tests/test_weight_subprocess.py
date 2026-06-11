# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the GUI-owned weight-subprocess lifecycle.

Covers the runtime activation/deactivation path of the
``weight_scan_enabled`` toggle: when the user re-enables the scan at
runtime, the GUI itself spawns ``weight.py`` (the launcher
``main.py`` only acts at boot).

Tests intentionally avoid instantiating ``WeighingApp`` (it would boot
Tk + the websocket server). Instead they call the methods unbound
against a ``SimpleNamespace`` mock for ``self``.
"""

import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from gui import WeighingApp


# ---------------------------------------------------------------------------
# _weight_subprocess_argv
# ---------------------------------------------------------------------------

def test_argv_dev_mode_returns_python_and_script_path(monkeypatch):
    """Dev-Modus (sys.frozen ungesetzt) -> [python, .../sources/weight.py]."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    argv = WeighingApp._weight_subprocess_argv(SimpleNamespace())
    assert argv is not None
    assert argv[0] == sys.executable
    assert argv[1].endswith(os.path.join("sources", "weight.py"))
    assert os.path.isfile(argv[1])


def test_argv_packaged_with_existing_binary(monkeypatch, tmp_path):
    """Packaged (sys.frozen=True, weight-Binary existiert) -> [<bin>/weight]."""
    fake_exe = tmp_path / "gui"
    fake_exe.write_text("#!fake")
    fake_weight = tmp_path / ("weight.exe" if os.name == "nt" else "weight")
    fake_weight.write_text("#!fake")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    argv = WeighingApp._weight_subprocess_argv(SimpleNamespace())
    assert argv == [str(fake_weight)]


def test_argv_packaged_missing_binary_returns_none(monkeypatch, tmp_path):
    """Packaged, aber kein weight-Binary -> None (kein Crash, GUI warnt)."""
    fake_exe = tmp_path / "gui"
    fake_exe.write_text("#!fake")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    argv = WeighingApp._weight_subprocess_argv(SimpleNamespace())
    assert argv is None


# ---------------------------------------------------------------------------
# _stop_weight_subprocess
# ---------------------------------------------------------------------------

def test_stop_managed_is_noop_when_subprocess_is_none():
    """_stop_weight_subprocess delegiert an _stop_managed_subprocess."""
    app = SimpleNamespace(weight_subprocess=None)
    WeighingApp._stop_managed_subprocess(app, "weight_subprocess")
    assert app.weight_subprocess is None


def test_stop_managed_is_noop_when_subprocess_already_exited():
    """poll() != None -> nichts tun, kein Crash."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=2.0)
    assert proc.poll() is not None
    app = SimpleNamespace(weight_subprocess=proc)
    WeighingApp._stop_managed_subprocess(app, "weight_subprocess")
    assert app.weight_subprocess is None


@pytest.mark.skipif(os.name == "nt", reason="setsid/killpg sind POSIX-only")
def test_stop_managed_terminates_running_subprocess():
    """Echter sleep-Subprozess wird durch _stop_managed_subprocess beendet."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        preexec_fn=os.setsid,
    )
    time.sleep(0.1)
    assert proc.poll() is None

    app = SimpleNamespace(weight_subprocess=proc)
    WeighingApp._stop_managed_subprocess(app, "weight_subprocess")

    assert app.weight_subprocess is None
    proc.wait(timeout=2.0)
    assert proc.returncode is not None


# ---------------------------------------------------------------------------
# send_weight_shutdown — no-op-Pfade ohne ws_loop
# ---------------------------------------------------------------------------

def test_send_weight_shutdown_noop_without_ws_loop():
    """Wenn kein ws_loop läuft, früh raus — kein Crash."""
    app = SimpleNamespace(ws_loop=None)
    WeighingApp.send_weight_shutdown(app)
    # Wenn wir hier ankommen, hat send_weight_shutdown sauber returned.


# ---------------------------------------------------------------------------
# start_weight_subprocess — duplicate-start-Schutz
# ---------------------------------------------------------------------------

def test_start_returns_true_if_already_running():
    """Wenn weight_subprocess.poll() is None, kein doppelter Spawn."""
    fake_running = SimpleNamespace(poll=lambda: None)
    app = SimpleNamespace(weight_subprocess=fake_running)
    assert WeighingApp.start_weight_subprocess(app) is True
    # Subprozess-Slot unverändert (kein Re-Spawn).
    assert app.weight_subprocess is fake_running


def test_start_returns_false_when_argv_unresolvable():
    """argv-Resolution liefert None -> Start ohne Crash, False zurück.

    SimpleNamespace löst Methoden nicht über __class__ auf — daher die
    argv-Resolver-Funktion direkt am Namespace ablegen statt auf der
    WeighingApp-Klasse zu monkeypatchen.
    """
    app = SimpleNamespace(
        weight_subprocess=None,
        _weight_subprocess_argv=lambda: None,
    )
    assert WeighingApp.start_weight_subprocess(app) is False
    assert app.weight_subprocess is None
