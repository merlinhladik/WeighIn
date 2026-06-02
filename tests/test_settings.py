# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for ``shared.settings`` (persisted user-global toggle store).

Each test redirects ``$HOME`` to a tmp_path so the real
``~/.weighin/settings.json`` is never touched.
"""

import json
import os

import pytest

from shared.settings import (
    DEFAULTS,
    SETTINGS_DIR_NAME,
    SETTINGS_FILE_NAME,
    load_settings,
    save_settings,
    settings_path,
)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Redirect $HOME so no test touches the real settings file."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # On Windows, expanduser may consult USERPROFILE — keep both consistent.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


def test_settings_path_is_under_home(_isolated_home):
    expected = os.path.join(str(_isolated_home), SETTINGS_DIR_NAME, SETTINGS_FILE_NAME)
    assert settings_path() == expected


def test_load_returns_defaults_when_file_missing():
    assert load_settings() == DEFAULTS


def test_defaults_include_scanner_keys():
    """Sanity: shared.settings deklariert die scanner-Keys, die main.py + gui.py erwarten."""
    assert DEFAULTS["scanner_mode"] == "hotkey"
    # Index 0 = interne Cam, auf jedem MacBook vorhanden. Multi-Cam-Setups
    # setzen den Index manuell — Default 1 hätte Single-Cam-Systeme gebrochen.
    assert DEFAULTS["scanner_camera_index"] == 0
    assert DEFAULTS["weight_scan_enabled"] is True


def test_save_and_load_scanner_keys_roundtrip():
    save_settings({"scanner_mode": "camera", "scanner_camera_index": 3})
    loaded = load_settings()
    assert loaded["scanner_mode"] == "camera"
    assert loaded["scanner_camera_index"] == 3

    save_settings({"scanner_mode": "off"})
    loaded = load_settings()
    assert loaded["scanner_mode"] == "off"
    # Vorheriger Index bleibt erhalten — Update ist merge, kein replace.
    assert loaded["scanner_camera_index"] == 3


def test_load_returns_defaults_when_dir_missing():
    # Sanity: tmp_path/.weighin doesn't exist yet.
    assert not os.path.exists(os.path.dirname(settings_path()))
    assert load_settings() == DEFAULTS


def test_save_creates_dir_and_file(_isolated_home):
    save_settings({"weight_scan_enabled": False})

    assert os.path.isdir(os.path.join(str(_isolated_home), SETTINGS_DIR_NAME))
    assert os.path.isfile(settings_path())


def test_save_and_load_roundtrip():
    save_settings({"weight_scan_enabled": False})
    assert load_settings()["weight_scan_enabled"] is False

    save_settings({"weight_scan_enabled": True})
    assert load_settings()["weight_scan_enabled"] is True


def test_load_merges_partial_file_with_defaults():
    # Persist only a single key (simulate a future-key-only file or a
    # partial first-time write).
    os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
    with open(settings_path(), "w", encoding="utf-8") as f:
        json.dump({"some_future_key": 42}, f)

    loaded = load_settings()
    # Defaults preserved for keys the file doesn't have:
    assert loaded["weight_scan_enabled"] is True
    # Unknown key passed through unchanged:
    assert loaded["some_future_key"] == 42


def test_load_falls_back_to_defaults_on_malformed_json():
    os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
    with open(settings_path(), "w", encoding="utf-8") as f:
        f.write("this is not json {")
    assert load_settings() == DEFAULTS


def test_save_atomic_no_partial_file_on_disk(_isolated_home):
    """After a successful save, no .tmp files linger in the settings dir."""
    save_settings({"weight_scan_enabled": False})

    settings_dir = os.path.join(str(_isolated_home), SETTINGS_DIR_NAME)
    entries = os.listdir(settings_dir)
    # Only the final settings.json, no half-written temp.
    assert entries == [SETTINGS_FILE_NAME]


def test_save_overwrites_existing_file_without_dropping_unknown_keys():
    # Pre-seed with an unknown key plus a known one in non-default state.
    os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
    with open(settings_path(), "w", encoding="utf-8") as f:
        json.dump({"weight_scan_enabled": False, "kept": "yes"}, f)

    save_settings({"weight_scan_enabled": True})

    loaded = load_settings()
    assert loaded["weight_scan_enabled"] is True
    assert loaded["kept"] == "yes"
