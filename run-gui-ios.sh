#!/bin/sh
# Opens the Dithered QR interface on iPhone and iPad, inside a-Shell.
#
# iOS has no Tkinter and no way to open a native window from a-Shell, so the
# interface is a local web page: this starts a server on the loopback address
# and points Safari at it. Nothing leaves the device.
#
#   sh run-gui-ios.sh
#   sh run-gui-ios.sh --port 9000
#   sh run-gui-ios.sh --no-open      start the server without opening Safari

set -e

PROJECT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$PROJECT_DIR"

PORT=8765
OPEN=1
while [ $# -gt 0 ]; do
    case "$1" in
        --port)    PORT="${2:-8765}"; shift 2 ;;
        --no-open) OPEN=0; shift ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1 (use --help)" >&2; exit 2 ;;
    esac
done

PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
    echo "Python was not found. Install a-Shell from the App Store, then run: sh install-ios.sh" >&2
    exit 1
fi

if ! $PY -c 'import segno' >/dev/null 2>&1; then
    echo "Dependencies are missing. Run this first:" >&2
    echo "  sh install-ios.sh" >&2
    exit 1
fi

URL="http://127.0.0.1:$PORT"

cat <<FINE

Dithered QR — web interface
  address    $URL
  saves to   $PROJECT_DIR

  IMPORTANT, on iPhone and iPad: iOS suspends apps that go to the background,
  and a suspended a-Shell means a stopped server. Keep both on screen at once:

    iPad    open Safari in Split View next to a-Shell
    iPhone  the server may pause when you switch to Safari; if the page stops
            responding, go back to a-Shell for a moment and reload. If it gets
            in the way, use the command line instead:
              python3 dithered_qr.py "https://example.com" photo.jpg -o qr.png

  Readability cannot be checked on iOS: no QR decoder can be installed there.
  Test the generated code with your camera before using it.

  Press Ctrl+C to stop the server.

FINE

if [ "$OPEN" -eq 1 ] && command -v open >/dev/null 2>&1; then
    # Safari viene aperta dopo un attimo, quando il server e' gia' in ascolto.
    (sleep 2; open "$URL" >/dev/null 2>&1 || true) &
fi

exec $PY webgui.py --port "$PORT" --save-dir "$PROJECT_DIR"
