#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -d "$SCRIPT_DIR/sources/venv" ]]; then
  VENV_DIR="$SCRIPT_DIR/sources/venv/"
else
  echo "Kein venv gefunden. Erwartet: $SCRIPT_DIR/venv oder $SCRIPT_DIR/.venv" >&2
  exit 1
fi

start_terminal() {
  local title="$1"
  local cmd="$2"

    qterminal -d -e bash -lc "source '$VENV_DIR/bin/activate' && cd '$SCRIPT_DIR' && $cmd; exec bash" &
}

start_terminal "gui.py" "python sources/gui.py"
start_terminal "real_scanner.py" "sudo \"$VENV_DIR/bin/python\" sources/real_scanner.py"
sleep 2
start_terminal "weight.py" "python sources/weight.py"


echo "3 Terminals wurden gestartet."