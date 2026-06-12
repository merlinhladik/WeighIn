#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: CC0-1.0
#
# WSP_Weighin_build.sh — Build der WeighIn-Station als ausfuehrbare Binaries
# (Linux + macOS). Das Windows-Pendant ist WSP_Weighin_build.ps1.
#
# WeighIn laeuft als VIER PyInstaller-Binaries, die nebeneinander im selben
# Ordner liegen muessen: der Launcher (main -> "WeighIn") spawnt gui / weight /
# real_scanner aus os.path.dirname(sys.executable). Dieses Skript baut alle
# vier und legt sie in dist/<os>/WeighIn/ ab.
#
# Aufruf:
#   ./WSP_Weighin_build.sh                # setup + build (Default)
#   ./WSP_Weighin_build.sh setup          # nur venv + Abhaengigkeiten
#   ./WSP_Weighin_build.sh build          # nur PyInstaller (venv muss stehen)
#   ./WSP_Weighin_build.sh clean          # dist/ + build/ entfernen
#
# macOS: delegiert an WeighIn/scripts/build-macos.sh (erzeugt ein .app-Bundle
#        mit den noetigen TCC-/Kamera-Berechtigungen — siehe dortige Doku).
# Linux: erzeugt vier --onefile-Binaries in dist/linux/WeighIn/.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEIGHIN_DIR="$SCRIPT_DIR/WeighIn"
SOURCES_DIR="$WEIGHIN_DIR/sources"

PYTHON_BIN="${PYTHON_BIN:-python3.13}"

log()  { printf '\033[1;34m[%s]\033[0m %s\n' "$1" "$2"; }
warn() { printf '\033[1;33m[%s]\033[0m %s\n' "$1" "$2" >&2; }
fail() { printf '\033[1;31m[%s]\033[0m %s\n' "$1" "$2" >&2; exit 1; }

[[ -d "$WEIGHIN_DIR" ]] || fail "PRE" "WeighIn/ nicht neben dem Skript gefunden ($WEIGHIN_DIR)."

OS="$(uname)"

# ---------------------------------------------------------------------------
# macOS -> bestehende, ausgereifte Pipeline (TCC/Kamera/codesign) wiederverwenden
# ---------------------------------------------------------------------------
if [[ "$OS" == "Darwin" ]]; then
    MAC_PIPELINE="$WEIGHIN_DIR/scripts/build-macos.sh"
    [[ -x "$MAC_PIPELINE" ]] || fail "PRE" "macOS-Pipeline fehlt/nicht ausfuehrbar: $MAC_PIPELINE"

    case "${1:-default}" in
        default)        log "MAC" "Delegiere an build-macos.sh (setup build package)"
                        exec "$MAC_PIPELINE" setup build package ;;
        setup)          exec "$MAC_PIPELINE" setup ;;
        build|package)  exec "$MAC_PIPELINE" package ;;
        clean)          exec "$MAC_PIPELINE" clean ;;
        *)              exec "$MAC_PIPELINE" "$@" ;;
    esac
fi

# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------
[[ "$OS" == "Linux" ]] || fail "PRE" "Nicht unterstuetztes OS: $OS. Fuer Windows WSP_Weighin_build.ps1 nutzen."

VENV_DIR="$WEIGHIN_DIR/.venv-linux"
DIST_DIR="$WEIGHIN_DIR/dist/linux"
BUILD_DIR="$WEIGHIN_DIR/build/linux"
OUT_DIR="$DIST_DIR/WeighIn"

COMPONENTS=(gui weight real_scanner)   # Subprozesse (--onefile)
LAUNCHER_NAME="WeighIn"                 # aus main.py

activate_venv() {
    [[ -d "$VENV_DIR" ]] || fail "PRE" "Kein venv unter $VENV_DIR. Erst 'setup' ausfuehren."
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
}

stage_setup() {
    log "SETUP" "venv unter $VENV_DIR"
    command -v "$PYTHON_BIN" >/dev/null 2>&1 || PYTHON_BIN="python3"
    command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "PRE" "Kein python3(.13) gefunden."

    [[ -d "$VENV_DIR" ]] || "$PYTHON_BIN" -m venv "$VENV_DIR"
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    python -m pip install --upgrade pip
    python -m pip install -r "$WEIGHIN_DIR/requirements.txt"

    python -c "import tkinter" 2>/dev/null \
        || warn "SETUP" "tkinter fehlt. Auf Debian/Ubuntu: 'sudo apt install python3-tk'."
    log "SETUP" "fertig"
}

# Gemeinsame PyInstaller-Flags fuer Linux:
#  - pygrabber (Windows-Kamera) + AVFoundation (macOS) werden ausgeschlossen,
#    Linux nutzt V4L via cv2 / v4l2-ctl.
_pyi_common=(
    --noconfirm
    --paths "$SOURCES_DIR"
    --exclude-module pygrabber
    --exclude-module AVFoundation
    --log-level WARN
)

stage_build() {
    log "BUILD" "PyInstaller (4 Komponenten) -> $OUT_DIR"
    activate_venv
    command -v pyinstaller >/dev/null 2>&1 || fail "BUILD" "pyinstaller fehlt — 'setup' erneut laufen lassen."

    rm -rf "$DIST_DIR" "$BUILD_DIR"
    mkdir -p "$OUT_DIR" "$BUILD_DIR"

    # Launcher
    log "BUILD" "Komponente: $LAUNCHER_NAME (Launcher / main.py)"
    pyinstaller "${_pyi_common[@]}" \
        --distpath "$OUT_DIR" \
        --workpath "$BUILD_DIR/main" \
        --specpath "$BUILD_DIR/main" \
        --onefile --name "$LAUNCHER_NAME" \
        "$SOURCES_DIR/main.py"

    # Subprozesse
    for comp in "${COMPONENTS[@]}"; do
        log "BUILD" "Komponente: $comp"
        pyinstaller "${_pyi_common[@]}" \
            --distpath "$OUT_DIR" \
            --workpath "$BUILD_DIR/$comp" \
            --specpath "$BUILD_DIR/$comp" \
            --onefile --name "$comp" \
            "$SOURCES_DIR/${comp}.py"
    done

    log "BUILD" "Fertig. Binaries:"
    ls -1 "$OUT_DIR"
    log "BUILD" "Start: '$OUT_DIR/$LAUNCHER_NAME'"
    warn "BUILD" "Hotkey-Scanner braucht root (keyboard-Lib) — der Launcher eskaliert per sudo/pkexec."
    warn "BUILD" "Laufzeit-Tools: v4l-utils (Kamera-Liste), libgl1 (cv2). Bei Bedarf nachinstallieren."
}

stage_clean() {
    log "CLEAN" "Entferne dist/linux, build/linux"
    rm -rf "$DIST_DIR" "$BUILD_DIR"
    log "CLEAN" "fertig"
}

case "${1:-default}" in
    default)  stage_setup; stage_build ;;
    setup)    stage_setup ;;
    build)    stage_build ;;
    clean)    stage_clean ;;
    *)        fail "ARG" "Unbekannt: $1 (default|setup|build|clean)" ;;
esac
