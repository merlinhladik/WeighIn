#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -d "$SCRIPT_DIR/sources/venv" ]]; then
  VENV_DIR="$SCRIPT_DIR/venv"
else
  echo "Kein venv gefunden. Erwartet: $SCRIPT_DIR/venv oder $SCRIPT_DIR/.venv" >&2
  exit 1
fi

start_terminal() {
  local title="$1"
  local cmd="$2"

  if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="$title" -- bash -lc "source '$VENV_DIR/bin/activate' && cd '$SCRIPT_DIR' && $cmd; exec bash"
  elif command -v konsole >/dev/null 2>&1; then
    konsole --new-tab -p tabtitle="$title" -e bash -lc "source '$VENV_DIR/bin/activate' && cd '$SCRIPT_DIR' && $cmd; exec bash"
  elif command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal --title="$title" --command="bash -lc \"source '$VENV_DIR/bin/activate' && cd '$SCRIPT_DIR' && $cmd; exec bash\""
  elif command -v xterm >/dev/null 2>&1; then
    xterm -T "$title" -e bash -lc "source '$VENV_DIR/bin/activate' && cd '$SCRIPT_DIR' && $cmd; exec bash" &
  else
    echo "Kein unterstützter Terminal-Emulator gefunden (gnome-terminal, konsole, xfce4-terminal, xterm)." >&2
    exit 1
  fi
}

start_terminal "gui.py" "python sources/gui.py"
start_terminal "weight.py" "python sources/weight.py"
start_terminal "real_scanner.py" "sudo \"$VENV_DIR/bin/python\" sources/real_scanner.py"

echo "3 Terminals wurden gestartet."