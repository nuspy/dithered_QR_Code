#!/usr/bin/env bash
# Opens the Dithered QR interface on Linux and macOS.
#
# Uses the project's virtual environment if present, otherwise the Python on
# PATH. Starts the desktop window; falls back to the local web interface when
# Tkinter is missing, which on Linux is a separate package.
#
#   ./run-gui.sh              desktop window
#   ./run-gui.sh --web        browser interface
#   ./run-gui.sh --port 9000  browser interface on another port

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

WEB=0
PORT=8765
while [ $# -gt 0 ]; do
    case "$1" in
        --web)  WEB=1; shift ;;
        --port) PORT="${2:-8765}"; WEB=1; shift 2 ;;
        -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1 (use --help)" >&2; exit 2 ;;
    esac
done

if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
else
    PYTHON="$(command -v python3 || command -v python || true)"
    if [ -z "$PYTHON" ]; then
        echo "Python was not found. Run ./install.sh first." >&2
        exit 1
    fi
    echo "No .venv found, using $PYTHON (run ./install.sh to set one up)."
fi

if [ "$WEB" -eq 1 ]; then
    echo "Starting the web interface on http://127.0.0.1:$PORT"
    exec "$PYTHON" webgui.py --port "$PORT" --open
fi

# Su Linux Tkinter sta in un pacchetto separato e manca spesso: meglio dirlo e
# ripiegare sul browser che presentare una traccia di errore.
if ! "$PYTHON" -c "import tkinter" >/dev/null 2>&1; then
    echo "Tkinter is not installed; opening the web interface instead."
    echo "  Debian/Ubuntu: sudo apt-get install python3-tk"
    echo "  Fedora:        sudo dnf install python3-tkinter"
    echo "  Arch:          sudo pacman -S tk"
    echo "  macOS:         brew install python-tk"
    exec "$PYTHON" webgui.py --port "$PORT" --open
fi

# Senza display non c'e' finestra da aprire: succede via SSH, nei container e
# sui server. Il browser invece funziona, anche da un altro computer.
if [ "$(uname -s)" = "Linux" ] && [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    echo "No display detected (headless session); opening the web interface instead."
    echo "  If you are on SSH, forward the port:  ssh -L $PORT:127.0.0.1:$PORT <host>"
    exec "$PYTHON" webgui.py --port "$PORT"
fi

exec "$PYTHON" gui.py
