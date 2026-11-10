#!/bin/sh
# Installa dithered_qr su iPad e iPhone, dentro a-Shell (gratuita, App Store).
#
# Deliberatamente scritto in sh POSIX e senza ambienti virtuali: a-Shell non ha
# bash completa ne' venv, e la sua Python vive in una sandbox dove i pacchetti
# si installano direttamente.
#
# Su iOS non esistono OpenCV ne' ZBar: sono estensioni native, e la piattaforma
# non permette di compilarle o caricarle. Il generatore funziona per intero lo
# stesso, con due rinunce dichiarate:
#   - la verifica automatica di leggibilita' non e' disponibile;
#   - l'inquadratura non cerca il volto e ricade sul centro (--center, --zoom).
#
#   sh install-ios.sh

set -e

C_OK=''; C_WARN=''; C_OFF=''
if [ -t 1 ]; then C_OK=$(printf '\033[32m'); C_WARN=$(printf '\033[33m'); C_OFF=$(printf '\033[0m'); fi
step() { printf '\n==> %s\n' "$1"; }
ok()   { printf '    %s%s%s\n' "$C_OK" "$1" "$C_OFF"; }
warn() { printf '    %s%s%s\n' "$C_WARN" "$1" "$C_OFF"; }
die()  { printf '\nErrore: %s\n' "$1" >&2; exit 1; }

PROJECT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$PROJECT_DIR"

# --------------------------------------------------------------------------

step "Interprete Python"
PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[ -n "$PY" ] || die "nessun Python trovato. Su iOS installa a-Shell dall'App Store."

$PY -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)' 2>/dev/null \
    || die "serve Python 3.10 o superiore ($($PY -V 2>&1))."
ok "$($PY -V 2>&1)"

# --------------------------------------------------------------------------

step "Dipendenze"
# numpy e Pillow sono gia' dentro a-Shell: sono estensioni native, e li' non si
# possono aggiungere dopo. Se mancano si prova comunque, ma senza illusioni.
for modulo in numpy PIL; do
    if $PY -c "import $modulo" >/dev/null 2>&1; then
        ok "$modulo presente"
    else
        warn "$modulo assente, provo a installarlo"
        if [ "$modulo" = PIL ]; then pacchetto="Pillow"; else pacchetto="numpy"; fi
        $PY -m pip install "$pacchetto" 2>/dev/null || pip install "$pacchetto" 2>/dev/null || true
        $PY -c "import $modulo" >/dev/null 2>&1 \
            || die "$modulo non e' installabile in questo ambiente. Su iOS serve a-Shell, che lo include gia'."
    fi
done

# segno e' puro Python: si installa ovunque, iOS compreso.
if $PY -c 'import segno' >/dev/null 2>&1; then
    ok "segno presente"
else
    # Gli errori di pip si mostrano invece di nasconderli: quasi sempre dicono
    # gia' cosa fare (in a-Shell il comando e' `pip`, sulle distribuzioni
    # recenti serve un ambiente virtuale per via di PEP 668).
    installato=0
    if $PY -m pip install segno; then
        installato=1
    elif command -v pip >/dev/null 2>&1 && pip install segno; then
        installato=1
    fi
    if [ "$installato" -eq 0 ] || ! $PY -c 'import segno' >/dev/null 2>&1; then
        die "installazione di segno non riuscita (vedi l'errore di pip qui sopra).
       In a-Shell:              pip install segno
       Su Linux o macOS:        crea un ambiente virtuale con ./install.sh
       Se pip parla di 'externally-managed-environment', usa un ambiente
       virtuale invece di installare nel Python di sistema."
    fi
    ok "segno installato"
fi

# --------------------------------------------------------------------------

step "Prova di generazione"
$PY - <<'PROBE'
import sys, tempfile
from pathlib import Path
import numpy as np
from PIL import Image
import imaging, verify
from dithered_qr import Settings, generate

side = 360
y, x = np.mgrid[0:side, 0:side]
img = 40 + 170 * (y / side)
img[(x - side*0.5)**2 + (y - side*0.45)**2 < (side*0.3)**2] = 230
tmp = Path(tempfile.gettempdir()) / "dqr_probe.png"
Image.fromarray(np.clip(img, 0, 255).astype("uint8"), "L").save(tmp)

res = generate("https://esempio.it/prova", tmp, Settings(min_version=7))
print(f"    backend immagine: {imaging.backend()}")
print(f"    decoder QR:       {', '.join(imaging.decoders()) or 'nessuno (atteso su iOS)'}")
print(f"    simbolo:          versione {res.version}, {res.modules} moduli, fedelta {res.fidelity:.2f}")
if res.fidelity < 0.2:
    print("    ERRORE: l'immagine non e' stata incisa nel codice", file=sys.stderr)
    raise SystemExit(1)
tmp.unlink(missing_ok=True)
PROBE

# --------------------------------------------------------------------------

printf '\n%sInstallazione completata.%s\n\n' "$C_OK" "$C_OFF"
cat <<'FINE'
  Interfaccia grafica (pagina web locale, si apre in Safari):
    sh run-gui-ios.sh

  Riga di comando:
    python3 dithered_qr.py "https://esempio.it" foto.jpg -o qr.png

  Su iOS tieni presente che:

  - La verifica di leggibilita' non e' disponibile: OpenCV e ZBar sono
    estensioni native che iOS non permette. Il programma lo dichiara e prosegue.
    PROVA SEMPRE IL CODICE CON LA FOTOCAMERA prima di usarlo davvero.

  - L'inquadratura non cerca il volto. Se il soggetto non e' al centro:
      python3 dithered_qr.py "testo" foto.jpg -o qr.png --center 0.5,0.3 --zoom 1.5

  - Per lavorare sulle tue foto, in a-Shell:
      pickFolder                 collega una cartella dell'app File
      showmarkup qr.png          apre l'anteprima del risultato
      open qr.png                lo passa ad un'altra app

  - Il dithering e' un ciclo Python: su iPhone un codice grande puo' richiedere
    qualche secondo. Con --scale 7 e --min-version 10 va piu' spedito.

  - Con l'interfaccia web, tieni a-Shell e Safari sullo schermo insieme
    (Split View su iPad): iOS sospende le app in secondo piano, e a-Shell
    sospesa vuol dire server fermo.
FINE
