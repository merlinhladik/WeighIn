#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -d "$SCRIPT_DIR/sources/venv" ]]; then
  VENV_DIR="$SCRIPT_DIR/sources/venv/"
else
  echo "Kein venv gefunden. Erwartet: $SCRIPT_DIR/venv oder $SCRIPT_DIR/.venv" >&2
  exit 1
fi

source "$VENV_DIR/bin/activate"
cd "$SCRIPT_DIR"

"$VENV_DIR/bin/python" sources/gui.py &
"$VENV_DIR/bin/python" sources/real_scanner.py &
"$VENV_DIR/bin/python" sources/weight.py &