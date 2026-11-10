# Installazione

Tre installer, uno per piattaforma. Ognuno verifica Python, prepara l'ambiente,
installa le dipendenze e **genera un codice di prova rileggendolo**: l'esito
dell'installazione è verificato, non solo dichiarato. Sono tutti rieseguibili:
se trovano l'ambiente già pronto lo aggiornano.

| piattaforma | installazione | apertura interfaccia | Python installato dallo script |
|---|---|---|---|
| Windows | `.\install.ps1` | `.\run-gui.ps1` | sì, con winget |
| Linux | `./install.sh` | `./run-gui.sh` | sì, con il gestore della distribuzione |
| macOS | `./install.sh` | `./run-gui.sh` | sì, con Homebrew |
| iPhone, iPad | `sh install-ios.sh` | `sh run-gui-ios.sh` | no: lo fornisce a-Shell |

Serve **Python 3.10 o superiore**.

## Le due interfacce

`run-gui` apre la **finestra nativa** (Tkinter, con i dialoghi di sistema per
aprire e salvare). Ripiega da solo sulla **pagina web locale** in tre casi:
Tkinter non installato, nessuna sessione grafica (SSH, container, server),
oppure iOS, dove Tkinter non esiste affatto. La si può chiedere esplicitamente:

```powershell
.\run-gui.ps1 -Web              # Windows
```
```bash
./run-gui.sh --web              # Linux, macOS
./run-gui.sh --port 9000        # su un'altra porta
```

Il server web ascolta **solo su 127.0.0.1**: non è raggiungibile dagli altri
dispositivi della rete. Da remoto conviene inoltrare la porta invece di
esporlo: `ssh -L 8765:127.0.0.1:8765 <host>`.

Su Linux Tkinter è un pacchetto a parte e l'installer lo aggiunge
(`python3-tk`, `python3-tkinter`, `tk` secondo la distribuzione). Se non ci
riesce, lo dice e resta la pagina web, che non richiede nulla.

---

## Windows

```powershell
.\install.ps1
```

Se manca Python lo installa con `winget` (`Python.Python.3.12`); se winget non
c'è, lo script si ferma e indica il link al programma d'installazione. Crea
`.venv` nella cartella del progetto.

```powershell
.\install.ps1 -Minimal   # solo il nucleo, senza OpenCV né ZBar
.\install.ps1 -Force     # ricrea l'ambiente da zero
.\install.ps1 -SkipPython
```

Poi:

```powershell
.\.venv\Scripts\python.exe dithered_qr.py "https://esempio.it" foto.jpg -o qr.png
```

**Se PowerShell rifiuta di eseguire lo script** (criteri di esecuzione):

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**Se l'installer segnala che ZBar non si carica**: il wheel di `pyzbar` porta con
sé `libzbar`, ma quella DLL è compilata con il runtime Visual C++ 2013, che
Windows non ha di serie.

```powershell
winget install Microsoft.VCRedist.2013.x64
```

Senza ZBar tutto continua a funzionare, ma la verifica usa il solo decoder
OpenCV, che è più indulgente: i punteggi risultano un po' ottimistici.

---

## Linux

```bash
chmod +x install.sh
./install.sh
```

Riconosce `apt-get`, `dnf`, `yum`, `pacman`, `zypper` e `apk`. Installa, se
mancano: Python, `python3-venv`, la libreria nativa `libzbar` (senza la quale
`pyzbar` si installa ma non si carica) e le librerie grafiche che il wheel di
OpenCV si aspetta — quelle che nelle immagini Docker e sui server senza desktop
non ci sono.

```bash
./install.sh --minimal    # solo il nucleo
./install.sh --force      # ricrea l'ambiente
./install.sh --no-sudo    # non toccare i pacchetti di sistema
./install.sh --no-python  # non installare Python nemmeno se manca
```

Per i pacchetti di sistema serve `sudo`. Senza, lo script prosegue lo stesso e
segnala cosa manca — utile se non si hanno i privilegi: il generatore funziona
comunque, si perde solo il decoder ZBar.

Su architetture per cui non esiste un wheel di OpenCV (ARM a 32 bit, musl, BSD)
l'installazione completa fallirebbe: lo script se ne accorge e **ripiega da solo
sul nucleo**, che basta a generare i codici.

Poi:

```bash
./.venv/bin/python dithered_qr.py "https://esempio.it" foto.jpg -o qr.png
```

---

## macOS

Lo stesso script:

```bash
chmod +x install.sh
./install.sh
```

Usa Homebrew per Python e per `zbar`. Se Homebrew non c'è, installalo da
[brew.sh](https://brew.sh) oppure prendi Python da python.org e rilancia con
`--no-python`.

**Su Apple Silicon** Homebrew installa in `/opt/homebrew`, dove il caricatore
dinamico non guarda: `pyzbar` trova `libzbar` solo se glielo si dice. L'installer
lo rileva e stampa la riga da aggiungere a `~/.zshrc`:

```bash
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH"
```

---

## iPhone e iPad

Serve **[a-Shell](https://apps.apple.com/app/a-shell/id1473805438)** (gratuita):
include Python con numpy e Pillow già dentro, che è esattamente ciò che non si
potrebbe installare dopo.

1. Installa a-Shell dall'App Store.
2. Copia la cartella del progetto in `~/Documents` (con l'app File, oppure
   `pickFolder` da a-Shell per collegare una cartella iCloud o Drive).
3. Nella cartella del progetto:

```sh
sh install-ios.sh        # installa segno e prova la generazione
sh run-gui-ios.sh        # apre l'interfaccia in Safari
```

L'interfaccia è una pagina servita da a-Shell su `127.0.0.1`: niente esce dal
dispositivo. Il pulsante **Save** scrive il PNG nella cartella del progetto —
così lo ritrovi nell'app File — e lo passa anche a Safari, che apre il pannello
di condivisione per salvarlo nelle Foto o inviarlo.

> **iOS sospende le app in secondo piano, e a-Shell sospesa vuol dire server
> fermo.** Su iPad tieni Safari in Split View accanto ad a-Shell. Su iPhone,
> se la pagina smette di rispondere, torna un attimo su a-Shell e ricarica;
> se dà troppo fastidio, usa la riga di comando.

### Cosa cambia su iOS

OpenCV e ZBar sono estensioni native: iOS non permette di compilarle né di
caricarle, quindi lì non esistono. Il generatore funziona **per intero** lo
stesso — la parte che disegna il codice è tutta numpy e Pillow — ma con due
rinunce, che il programma dichiara a ogni esecuzione invece di nasconderle:

- **niente verifica automatica di leggibilità**, perché non c'è alcun decoder QR
  da usare come giudice. Il programma lo scrive e prosegue senza irrigidire i
  parametri, il che sarebbe il rischio peggiore: scambiare "non misurabile" per
  "illeggibile" e rovinare l'immagine per un problema inesistente;
- **niente inquadratura automatica sul volto**: il ritaglio ricade sul centro e
  si regola a mano.

```sh
python3 dithered_qr.py "https://esempio.it" foto.jpg -o qr.png --center 0.5,0.3 --zoom 1.5
showmarkup qr.png     # anteprima
open qr.png           # passa il file a un'altra app
```

**Su iOS prova sempre il codice con la fotocamera prima di usarlo**: senza
verifica automatica, quella è l'unica prova che hai.

Il dithering è un ciclo Python: su iPhone un simbolo grande richiede qualche
secondo. Con `--scale 7 --min-version 10` è sensibilmente più rapido.

> Se preferisci generare sul computer e usare il telefono solo per l'anteprima,
> è la strada più comoda: su desktop hai anche la verifica.

---

## Installazione manuale

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windows: .venv\Scripts\pip
```

Oppure il solo nucleo, senza estensioni native:

```bash
.venv/bin/pip install -r requirements-minimal.txt
```

| pacchetto | serve a | se manca |
|---|---|---|
| `segno` | costruire il simbolo QR | **indispensabile** |
| `Pillow` | leggere e scrivere immagini | **indispensabile** |
| `numpy` | dithering e composizione | **indispensabile** |
| `opencv-python` | secondo decoder, rilevamento volto, velocità | tutto funziona, in puro numpy/Pillow |
| `pyzbar` | decoder ZBar, il più severo | la verifica resta col solo OpenCV |
| `tkinter` | finestra nativa (libreria standard, su Linux pacchetto a parte) | resta la pagina web |

L'interfaccia web non ha dipendenze oltre al nucleo: usa `http.server` della
libreria standard.

---

## Verificare l'installazione

```bash
python -m pytest -q          # 38 test
python -c "import imaging; print(imaging.backend(), imaging.decoders())"
python -c "import tkinter; print('finestra nativa disponibile')"
```

Il secondo comando dice quale percorso è attivo (`opencv` oppure
`numpy/pillow`) e quali decoder sono utilizzabili.

---

## Problemi noti

**`externally-managed-environment` quando installi con pip.** Le distribuzioni
recenti (Debian 12, Ubuntu 23.04+, Fedora 38+) impediscono a pip di scrivere nel
Python di sistema. Usa un ambiente virtuale: è ciò che gli installer fanno da
soli.

**Il rilevamento del volto non funziona anche se OpenCV è installato.** OpenCV 5
ha rimosso `CascadeClassifier` e i classificatori Haar. `requirements.txt` è
fermo alla serie 4 apposta; se hai OpenCV 5 nell'ambiente:

```bash
pip install "opencv-python>=4.8,<5"
```

Il resto (verifica, elaborazione immagine) funziona anche con OpenCV 5: il
programma se ne accorge e avvisa soltanto per l'inquadratura.

**`ImportError: libGL.so.1`** su server e container: mancano le librerie
grafiche che il wheel di OpenCV richiede.

```bash
sudo apt-get install libgl1 libglib2.0-0     # Debian, Ubuntu
sudo dnf install mesa-libGL glib2            # Fedora
```

In alternativa `pip install opencv-python-headless`, che non ne ha bisogno.

**pyzbar si installa ma non si importa.** Manca la libreria nativa: su Linux
`libzbar0` (o `zbar`), su macOS `brew install zbar`, su Windows il runtime
Visual C++ 2013.

---

## Cosa è stato provato davvero

Onestà sulle verifiche, perché "dovrebbe funzionare" e "l'ho visto funzionare"
sono cose diverse:

| ambiente | esito |
|---|---|
| Windows 11, Python 3.12 | `install.ps1` eseguito: ambiente creato, ZBar e OpenCV attivi, codice di prova riletto |
| Ubuntu 24.04, Python 3.13 | `install.sh` eseguito senza privilegi: ripiego su OpenCV senza ZBar gestito, codice di prova riletto |
| Ubuntu 24.04, solo nucleo | `install.sh --minimal`: nessun decoder, verifica saltata come previsto; il PNG prodotto è stato poi riletto altrove **al 100%** |
| `sh` POSIX (dash), ambiente con solo numpy e Pillow | `install-ios.sh` eseguito: `segno` installato, generazione riuscita |
| Finestra nativa, Windows 11 | avviata da `run-gui.ps1`; generazione, anteprima, **Save As…** e **New** esercitati da uno script: il file salvato è stato riletto e conteneva l'URL giusto |
| Pagina web, Windows 11 | server avviato, pagina e API provate: generazione, salvataggio, errori gestiti, e un nome tipo `../fuga.png` finisce **dentro** la cartella consentita |
| Pagina web, larghezza 360 e 390 px | resa in Edge: `scrollWidth == viewport` su entrambe, nessun elemento sfonda — **nessuno scorrimento orizzontale** |
| Ubuntu senza display | `gui.py` spiega il problema invece di mostrare l'errore Tcl; `run-gui.sh` passa da solo alla pagina web, che risponde |
| macOS | **non provato**: nessun Mac a disposizione. Lo script condivide con Linux tutta la struttura; i rami specifici (Homebrew, `DYLD_FALLBACK_LIBRARY_PATH`, `python-tk`) sono scritti ma non eseguiti |
| iPhone, iPad | **non provato su dispositivo**: verificata la logica degli script in un ambiente equivalente (sh POSIX, niente OpenCV né ZBar) e la resa della pagina alle larghezze di iPhone, ma non a-Shell reale né Safari su iOS |
