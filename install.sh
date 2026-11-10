#!/usr/bin/env bash
# Installa dithered_qr su Linux e macOS: Python (se manca), le librerie di
# sistema che servono a ZBar, l'ambiente virtuale e le dipendenze.
#
# Lo script e' rieseguibile: se trova gia' l'ambiente lo aggiorna. Al termine
# genera un codice di prova e lo rilegge, cosi' l'esito e' verificato e non solo
# dichiarato.
#
#   ./install.sh              installazione completa
#   ./install.sh --minimal    solo il nucleo, senza OpenCV ne' ZBar
#   ./install.sh --force      ricrea l'ambiente virtuale da zero
#   ./install.sh --no-python  non installare Python nemmeno se manca
#   ./install.sh --no-sudo    non usare sudo per i pacchetti di sistema

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
MIN_PY_MAJOR=3
MIN_PY_MINOR=10

MINIMAL=0
FORCE=0
INSTALL_PYTHON=1
USE_SUDO=1

for arg in "$@"; do
    case "$arg" in
        --minimal)   MINIMAL=1 ;;
        --force)     FORCE=1 ;;
        --no-python) INSTALL_PYTHON=0 ;;
        --no-sudo)   USE_SUDO=0 ;;
        -h|--help)   sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "opzione sconosciuta: $arg (usa --help)" >&2; exit 2 ;;
    esac
done

# Colori solo se stiamo scrivendo su un terminale.
if [ -t 1 ]; then
    C_STEP=$'\033[36m'; C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_DIM=$'\033[90m'; C_OFF=$'\033[0m'
else
    C_STEP=''; C_OK=''; C_WARN=''; C_DIM=''; C_OFF=''
fi
step() { printf '\n%s==> %s%s\n' "$C_STEP" "$1" "$C_OFF"; }
ok()   { printf '    %s%s%s\n' "$C_OK" "$1" "$C_OFF"; }
warn() { printf '    %s%s%s\n' "$C_WARN" "$1" "$C_OFF"; }
info() { printf '    %s%s%s\n' "$C_DIM" "$1" "$C_OFF"; }
die()  { printf '\n%sErrore: %s%s\n' "$C_WARN" "$1" "$C_OFF" >&2; exit 1; }

# --------------------------------------------------------------------------
# Piattaforma e gestore pacchetti
# --------------------------------------------------------------------------

OS="$(uname -s)"
case "$OS" in
    Linux)  PLATFORM=linux ;;
    Darwin) PLATFORM=macos ;;
    *)      die "sistema non gestito: $OS. Su iOS usa install-ios.sh." ;;
esac

PKG=""
if [ "$PLATFORM" = macos ]; then
    command -v brew >/dev/null 2>&1 && PKG=brew
else
    for candidate in apt-get dnf yum pacman zypper apk; do
        if command -v "$candidate" >/dev/null 2>&1; then PKG="$candidate"; break; fi
    done
fi

SUDO=""
if [ "$USE_SUDO" -eq 1 ] && [ "$(id -u)" -ne 0 ] && [ "$PKG" != brew ]; then
    command -v sudo >/dev/null 2>&1 && SUDO=sudo
fi

# Installa pacchetti di sistema; non fatale, il chiamante decide.
sys_install() {
    [ $# -gt 0 ] || return 0
    if [ -z "$PKG" ]; then
        warn "nessun gestore pacchetti riconosciuto: installa a mano $*"
        return 1
    fi
    info "$PKG: $*"
    case "$PKG" in
        apt-get) $SUDO apt-get update -qq && $SUDO apt-get install -y -qq "$@" ;;
        dnf)     $SUDO dnf install -y -q "$@" ;;
        yum)     $SUDO yum install -y -q "$@" ;;
        pacman)  $SUDO pacman -Sy --noconfirm --needed "$@" ;;
        zypper)  $SUDO zypper --non-interactive install "$@" ;;
        apk)     $SUDO apk add --quiet "$@" ;;
        brew)    brew install "$@" ;;
    esac
}

# --------------------------------------------------------------------------
# 1. Python
# --------------------------------------------------------------------------

py_ok() {
    "$1" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= ($MIN_PY_MAJOR, $MIN_PY_MINOR) else 1)" \
        >/dev/null 2>&1
}

find_python() {
    for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && py_ok "$candidate"; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

step "Ricerca di Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR} o superiore"
PYTHON="$(find_python || true)"

if [ -z "$PYTHON" ]; then
    [ "$INSTALL_PYTHON" -eq 1 ] || die "Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+ non trovato e --no-python e' attivo."
    step "Installazione di Python"
    case "$PKG" in
        apt-get) sys_install python3 python3-venv python3-pip || true ;;
        dnf|yum) sys_install python3 python3-pip || true ;;
        pacman)  sys_install python python-pip || true ;;
        zypper)  sys_install python3 python3-pip || true ;;
        apk)     sys_install python3 py3-pip || true ;;
        brew)    sys_install python@3.12 || true ;;
        *)       die "installa Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+ dal gestore pacchetti della tua distribuzione, poi riesegui." ;;
    esac
    PYTHON="$(find_python || true)"
    [ -n "$PYTHON" ] || die "Python risulta installato ma non raggiungibile. Apri un nuovo terminale e riprova."
fi
ok "$("$PYTHON" -V 2>&1) -> $PYTHON"

# --------------------------------------------------------------------------
# 2. Librerie di sistema
# --------------------------------------------------------------------------

step "Interfaccia grafica"
# Tkinter e' nella libreria standard ma le distribuzioni lo impacchettano a
# parte, e senza non si apre la finestra. Se non si riesce a installarlo resta
# comunque l'interfaccia web, che non ha bisogno di nulla.
if "$PYTHON" -c "import tkinter" >/dev/null 2>&1; then
    ok "Tkinter presente"
else
    case "$PKG" in
        apt-get) sys_install python3-tk || true ;;
        dnf|yum) sys_install python3-tkinter || true ;;
        pacman)  sys_install tk || true ;;
        zypper)  sys_install python3-tk || true ;;
        apk)     sys_install python3-tkinter || true ;;
        brew)    sys_install python-tk || true ;;
        *)       : ;;
    esac
    if "$PYTHON" -c "import tkinter" >/dev/null 2>&1; then
        ok "Tkinter installato"
    else
        warn "Tkinter non disponibile: la finestra nativa non si aprira'."
        warn "Resta l'interfaccia web: ./run-gui.sh --web"
    fi
fi

if [ "$MINIMAL" -eq 0 ]; then
    step "Librerie di sistema"
    # pyzbar e' solo un collegamento alla libreria nativa libzbar: senza quella,
    # l'import fallisce a runtime anche se pip dice di averlo installato.
    case "$PKG" in
        apt-get) sys_install libzbar0 || warn "libzbar non installata: ZBar non sara' disponibile" ;;
        dnf|yum) sys_install zbar     || warn "zbar non installata: ZBar non sara' disponibile" ;;
        pacman)  sys_install zbar     || warn "zbar non installata: ZBar non sara' disponibile" ;;
        zypper)  sys_install libzbar0 || warn "libzbar non installata: ZBar non sara' disponibile" ;;
        apk)     sys_install zbar     || warn "zbar non installata: ZBar non sara' disponibile" ;;
        brew)    sys_install zbar     || warn "zbar non installata: ZBar non sara' disponibile" ;;
        *)       warn "gestore pacchetti ignoto: per ZBar installa a mano libzbar" ;;
    esac

    # Le distribuzioni minimali (immagini Docker, server senza desktop) non hanno
    # le librerie grafiche che il wheel di OpenCV si aspetta di trovare.
    if [ "$PLATFORM" = linux ]; then
        case "$PKG" in
            apt-get) sys_install libgl1 libglib2.0-0 >/dev/null 2>&1 || true ;;
            dnf|yum) sys_install mesa-libGL glib2     >/dev/null 2>&1 || true ;;
        esac
    fi
fi

# --------------------------------------------------------------------------
# 3. Ambiente virtuale
# --------------------------------------------------------------------------

step "Ambiente virtuale in .venv"
if [ "$FORCE" -eq 1 ] && [ -d "$VENV_DIR" ]; then
    info "rimozione dell'ambiente esistente (--force)"
    rm -rf "$VENV_DIR"
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    if ! "$PYTHON" -m venv "$VENV_DIR" 2>/dev/null; then
        # Su Debian e derivate il modulo venv sta in un pacchetto a parte.
        warn "modulo venv assente, provo a installarlo"
        case "$PKG" in
            apt-get) sys_install python3-venv || true ;;
            *) : ;;
        esac
        "$PYTHON" -m venv "$VENV_DIR" || die "creazione dell'ambiente virtuale non riuscita."
    fi
    ok "creato"
else
    ok "gia' presente, verra' aggiornato"
fi

VENV_PY="$VENV_DIR/bin/python"

# --------------------------------------------------------------------------
# 4. Dipendenze
# --------------------------------------------------------------------------

step "Installazione delle dipendenze"
REQ="requirements.txt"
[ "$MINIMAL" -eq 1 ] && REQ="requirements-minimal.txt"
info "$REQ"

"$VENV_PY" -m pip install --upgrade pip --quiet
if ! "$VENV_PY" -m pip install -r "$PROJECT_DIR/$REQ" --quiet; then
    if [ "$MINIMAL" -eq 0 ]; then
        # Su architetture senza wheel di OpenCV (ARM a 32 bit, musl, BSD) la
        # compilazione fallisce: il nucleo pero' basta a generare i codici.
        warn "installazione completa non riuscita, ripiego sul nucleo"
        "$VENV_PY" -m pip install -r "$PROJECT_DIR/requirements-minimal.txt" --quiet \
            || die "installazione delle dipendenze non riuscita."
        MINIMAL=1
    else
        die "installazione delle dipendenze non riuscita."
    fi
fi
ok "installate"

# --------------------------------------------------------------------------
# 5. Controllo di ZBar
# --------------------------------------------------------------------------

if [ "$MINIMAL" -eq 0 ]; then
    step "Controllo del decoder ZBar"
    if "$VENV_PY" -c "from pyzbar import pyzbar" >/dev/null 2>&1; then
        ok "ZBar disponibile"
    elif [ "$PLATFORM" = macos ]; then
        # Homebrew su Apple Silicon installa in /opt/homebrew, dove il caricatore
        # dinamico non guarda: pyzbar trova la libreria solo se glielo si dice.
        BREW_LIB="$( (brew --prefix 2>/dev/null || echo /opt/homebrew) )/lib"
        if DYLD_FALLBACK_LIBRARY_PATH="$BREW_LIB" "$VENV_PY" -c "from pyzbar import pyzbar" >/dev/null 2>&1; then
            warn "ZBar funziona solo con DYLD_FALLBACK_LIBRARY_PATH impostata."
            warn "Aggiungi al tuo ~/.zshrc:"
            warn "  export DYLD_FALLBACK_LIBRARY_PATH=\"$BREW_LIB:\$DYLD_FALLBACK_LIBRARY_PATH\""
        else
            warn "ZBar non si carica: prova 'brew install zbar'."
            warn "Senza ZBar la verifica usa il solo decoder OpenCV, piu' indulgente."
        fi
    else
        warn "ZBar non si carica: manca la libreria nativa libzbar."
        warn "Senza ZBar la verifica usa il solo decoder OpenCV, piu' indulgente."
    fi
fi

# --------------------------------------------------------------------------
# 6. Prova sul campo
# --------------------------------------------------------------------------

step "Prova di generazione e rilettura"
cd "$PROJECT_DIR"
"$VENV_PY" - <<'PROBE'
import sys, tempfile
from pathlib import Path
import numpy as np
from PIL import Image
import imaging, verify
from dithered_qr import Settings, generate

side = 420
y, x = np.mgrid[0:side, 0:side]
img = 40 + 170 * (y / side)
img[(x - side*0.5)**2 + (y - side*0.45)**2 < (side*0.3)**2] = 230
tmp = Path(tempfile.gettempdir()) / "dqr_probe.png"
Image.fromarray(np.clip(img, 0, 255).astype("uint8"), "L").save(tmp)

testo = "https://esempio.it/prova"
res = generate(testo, tmp, Settings(min_version=7))
print(f"    backend immagine: {imaging.backend()}")
print(f"    decoder QR:       {', '.join(imaging.decoders()) or 'nessuno'}")
print(f"    simbolo:          versione {res.version}, {res.modules} moduli, fedelta {res.fidelity:.2f}")
if verify.available():
    if testo not in verify.decode(np.array(res.image.convert("L"))):
        print("    ERRORE: il codice di prova non si rilegge", file=sys.stderr)
        raise SystemExit(1)
    print("    rilettura:        riuscita")
else:
    print("    rilettura:        non verificabile (nessun decoder installato)")

try:
    import tkinter  # noqa: F401
    print("    interfacce:       finestra nativa e pagina web")
except ImportError:
    print("    interfacce:       solo pagina web (Tkinter assente)")
tmp.unlink(missing_ok=True)
PROBE

# --------------------------------------------------------------------------

chmod +x "$PROJECT_DIR/run-gui.sh" 2>/dev/null || true

printf '\n%sInstallazione completata.%s\n\n' "$C_OK" "$C_OFF"
echo "  Interfaccia grafica:"
echo "    ./run-gui.sh                 finestra nativa"
echo "    ./run-gui.sh --web           pagina web, anche da telefono"
echo ""
echo "  Riga di comando:"
echo "    ./.venv/bin/python dithered_qr.py \"https://esempio.it\" foto.jpg -o qr.png"
echo ""
echo "  Oppure attiva l'ambiente una volta sola:"
echo "    source .venv/bin/activate"
echo "    python dithered_qr.py \"https://esempio.it\" foto.jpg -o qr.png"
echo ""
