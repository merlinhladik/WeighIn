#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: CC0-1.0
#
# Lokale macOS-Pipeline für WeighIn.
# Stages: setup | lint | test | build | package | docs | all
# Aufruf: scripts/build-macos.sh [stage ...]
#         scripts/build-macos.sh                # entspricht "all"
#         scripts/build-macos.sh lint test      # nur einzelne Stages

set -euo pipefail

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv-macos"
DIST_DIR="$PROJECT_ROOT/dist/macos"
BUILD_DIR="$PROJECT_ROOT/build/macos"
SOURCES_DIR="$PROJECT_ROOT/sources"

BUNDLE_ID_PREFIX="team.topcc.weighin"
APP_NAME="WeighIn"
APP_BUNDLE="$DIST_DIR/${APP_NAME}.app"

PYTHON_BIN="${PYTHON_BIN:-python3.13}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf '\033[1;34m[%s]\033[0m %s\n' "$1" "$2"; }
warn() { printf '\033[1;33m[%s]\033[0m %s\n' "$1" "$2" >&2; }
fail() { printf '\033[1;31m[%s]\033[0m %s\n' "$1" "$2" >&2; exit 1; }

require_macos() {
    [[ "$(uname)" == "Darwin" ]] || fail "PRE" "Diese Pipeline ist macOS-spezifisch (uname=$(uname))."
}

ensure_python() {
    command -v "$PYTHON_BIN" >/dev/null 2>&1 \
        || fail "PRE" "$PYTHON_BIN nicht gefunden. Installiere via 'brew install python@3.13 python-tk@3.13' oder setze PYTHON_BIN=."
}

activate_venv() {
    [[ -d "$VENV_DIR" ]] || fail "PRE" "Kein venv unter $VENV_DIR. Stage 'setup' zuerst ausführen."
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
}

# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------
stage_setup() {
    log "SETUP" "venv anlegen unter $VENV_DIR"
    require_macos
    ensure_python

    if [[ ! -d "$VENV_DIR" ]]; then
        "$PYTHON_BIN" -m venv "$VENV_DIR"
    fi
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    python -m pip install --upgrade pip
    python -m pip install -r "$PROJECT_ROOT/requirements.txt"
    # Tooling für Lint/Test/Coverage zusätzlich
    python -m pip install ruff reuse pytest pytest-cov

    # Tk-Smoke-Test (häufigste Mac-Stolperfalle)
    if ! python -c "import tkinter" 2>/dev/null; then
        warn "SETUP" "tkinter ist nicht verfügbar. Auf macOS: 'brew install python-tk@3.13' und venv neu anlegen."
    fi
    log "SETUP" "fertig"
}

stage_lint() {
    log "LINT" "ruff + reuse"
    activate_venv

    local rc=0
    ruff check "$SOURCES_DIR" || rc=$?
    (cd "$PROJECT_ROOT" && reuse lint) || rc=$?

    # In .gitlab-ci.yml: allow_failure: true
    if [[ $rc -ne 0 ]]; then
        warn "LINT" "Lint-Probleme (allow_failure=true wie in CI)."
    fi
    log "LINT" "fertig"
}

stage_test() {
    log "TEST" "pytest"
    activate_venv

    (cd "$PROJECT_ROOT" && python -m pytest --cov=sources --cov-report=term-missing)
    log "TEST" "fertig"
}

stage_build() {
    log "BUILD" "Syntax-Check (compileall)"
    activate_venv

    (cd "$PROJECT_ROOT" && python -m compileall -q sources)
    log "BUILD" "fertig"
}

# ---------------------------------------------------------------------------
# Package: PyInstaller × 4 Komponenten
# ---------------------------------------------------------------------------
_pyinstaller_common=(
    --noconfirm
    --paths "$SOURCES_DIR"
    --exclude-module pygrabber
    # AVFoundation wird in list_available_cameras lazy via try/except importiert,
    # PyInstaller erkennt es daher nicht automatisch. Explizit einsammeln.
    --hidden-import AVFoundation
    --collect-submodules AVFoundation
    --log-level WARN
)

_per_component_specpath() {
    # PyInstaller schreibt sonst <name>.spec in cwd. In den Build-Ordner umleiten,
    # damit der Source-Tree sauber bleibt.
    echo "--specpath=$BUILD_DIR/$1"
}

_build_app_main() {
    log "PKG" "Baue ${APP_NAME}.app (Launcher)"
    # Eigener Workpath pro Komponente -> verhindert Konflikte zwischen vier
    # PyInstaller-Aufrufen, die sonst ueber gemeinsame Cache-Dateien stolpern.
    mkdir -p "$BUILD_DIR/main"
    pyinstaller \
        "${_pyinstaller_common[@]}" \
        --distpath "$DIST_DIR" \
        --workpath "$BUILD_DIR/main" \
        "$(_per_component_specpath main)" \
        --windowed \
        --name "$APP_NAME" \
        --osx-bundle-identifier "$BUNDLE_ID_PREFIX" \
        "$SOURCES_DIR/main.py"
}

_build_subprocess() {
    local component="$1"
    log "PKG" "Baue Subprozess-Binary: $component"
    # Kein --windowed: auf macOS erzwingt --windowed ein .app-Bundle.
    # Die Subprozesse leben als flache Mach-O-Binaries in Contents/MacOS/.
    mkdir -p "$BUILD_DIR/$component"
    pyinstaller \
        "${_pyinstaller_common[@]}" \
        --distpath "$DIST_DIR" \
        --workpath "$BUILD_DIR/$component" \
        "$(_per_component_specpath "$component")" \
        --onefile \
        --name "$component" \
        "$SOURCES_DIR/${component}.py"
}

_codesign_bundle() {
    log "PKG" "Bereinige extended attributes + ad-hoc Codesign"
    # Extended attributes (z.B. com.apple.quarantine, com.apple.macl) verhindern
    # Codesign mit "resource fork, Finder information, or similar detritus not allowed".
    xattr -cr "$APP_BUNDLE"

    # Ad-hoc-Signatur ("-") reicht, damit macOS-TCC dem Bundle eine stabile
    # Identität zuweist und die Kamera-Berechtigung an die App heften kann.
    if ! codesign --force --deep --sign - "$APP_BUNDLE" 2>/dev/null; then
        warn "PKG" "codesign fehlgeschlagen — TCC-Permission koennte instabil werden."
    fi
}

_inject_info_plist() {
    local plist="$APP_BUNDLE/Contents/Info.plist"
    [[ -f "$plist" ]] || fail "PKG" "Info.plist nicht gefunden: $plist"

    log "PKG" "Erweitere Info.plist um Berechtigungs-Strings"
    # PlistBuddy Add ist idempotent über Set; daher zuerst Set, sonst Add.
    set_or_add() {
        local key="$1" type="$2" value="$3"
        /usr/libexec/PlistBuddy -c "Set :$key $value" "$plist" 2>/dev/null \
            || /usr/libexec/PlistBuddy -c "Add :$key $type $value" "$plist"
    }

    set_or_add NSCameraUsageDescription string \
        "WeighIn benoetigt Kamerazugriff zum Lesen der Waagenanzeige und zum Scannen von QR-Codes."
    set_or_add NSAppleEventsUsageDescription string \
        "WeighIn nutzt AppleScript, um den QR-Scanner mit erhoehten Rechten zu starten."
    set_or_add LSMinimumSystemVersion string "11.0"
    set_or_add NSHighResolutionCapable bool true
}

_relocate_subprocesses() {
    log "PKG" "Verschiebe Subprozess-Binaries in App-Bundle"
    local target="$APP_BUNDLE/Contents/MacOS"
    for component in gui weight real_scanner; do
        local src="$DIST_DIR/$component"
        [[ -f "$src" ]] || fail "PKG" "Erwarte $src (PyInstaller --onefile Output)"
        mv "$src" "$target/$component"
        chmod +x "$target/$component"
    done
}

stage_package() {
    log "PKG" "Cleanup alter Build-Artefakte"
    activate_venv
    rm -rf "$DIST_DIR" "$BUILD_DIR"
    mkdir -p "$DIST_DIR" "$BUILD_DIR"

    (cd "$PROJECT_ROOT" && _build_app_main)
    for component in gui weight real_scanner; do
        (cd "$PROJECT_ROOT" && _build_subprocess "$component")
    done

    _relocate_subprocesses
    _inject_info_plist
    _codesign_bundle

    log "PKG" "Fertig: $APP_BUNDLE"
    log "PKG" "Start: open '$APP_BUNDLE'  oder  '$APP_BUNDLE/Contents/MacOS/$APP_NAME'"
    warn "PKG" "Hinweis: Beim ersten Start fragen Bedienungshilfen + Kamera nach Freigabe."
    warn "PKG" "         Das Paket 'keyboard' braucht Root oder Accessibility (siehe README/Analyse)."
}

stage_docs() {
    log "DOCS" "Doxygen"
    if ! command -v doxygen >/dev/null 2>&1; then
        warn "DOCS" "doxygen nicht gefunden. Installation: 'brew install doxygen'. Stage uebersprungen."
        return 0
    fi
    (cd "$PROJECT_ROOT" && doxygen Doxyfile)
    log "DOCS" "fertig"
}

stage_clean() {
    log "CLEAN" "Entferne dist/, build/, .venv-macos/"
    rm -rf "$DIST_DIR" "$BUILD_DIR" "$VENV_DIR"
    find "$PROJECT_ROOT" -name "__pycache__" -type d -prune -exec rm -rf {} +
    log "CLEAN" "fertig"
}

# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
run_stage() {
    case "$1" in
        setup)   stage_setup ;;
        lint)    stage_lint ;;
        test)    stage_test ;;
        build)   stage_build ;;
        package) stage_package ;;
        docs)    stage_docs ;;
        clean)   stage_clean ;;
        all)     stage_setup; stage_lint; stage_test; stage_build; stage_package; stage_docs ;;
        *)       fail "ARG" "Unbekannte Stage: $1 (setup|lint|test|build|package|docs|clean|all)" ;;
    esac
}

main() {
    require_macos
    if [[ $# -eq 0 ]]; then
        run_stage all
    else
        for stage in "$@"; do
            run_stage "$stage"
        done
    fi
}

main "$@"
