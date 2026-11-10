# dithered_qr

Genera un QR code scansionabile dentro cui vive una fotografia in dithering:
un ritratto in bianco e nero che *è* il codice, non un logo appiccicato sopra.

```powershell
.\install.ps1                    # Windows
```
```bash
./install.sh                     # Linux, macOS
sh install-ios.sh                # iPhone, iPad (a-Shell)
```

Gli installer preparano anche Python se manca. Dettagli e risoluzione problemi
in [INSTALL.md](INSTALL.md).

Poi, con l'interfaccia grafica (in inglese) oppure da riga di comando:

```powershell
.\run-gui.ps1                    # Windows
```
```bash
./run-gui.sh                     # Linux, macOS
sh run-gui-ios.sh                # iPhone, iPad — pagina web in Safari
```
```bash
python dithered_qr.py "https://esempio.it" ritratto.jpg -o qr.png
```

```
scritto qr.png  (1458x1458 px)
  versione 14, maschera 2, correzione H
  81 moduli, 3/9 px vincolati -> 78% dei pixel liberi per l'immagine
  fedelta' all'immagine 0.530 (margine 0.10)
  leggibilita' 100.0%  (10/10 prove, decoder: opencv+zbar)
```

## Come funziona

Uno scanner non guarda l'intero modulo QR: ricostruisce la griglia dai pattern
di servizio e ne campiona il centro. Ogni modulo viene quindi disegnato come un
blocco di `scale`×`scale` pixel di cui si vincola solo il nucleo centrale di
`core`×`core`: con i valori predefiniti resta libero circa l'80% dei pixel, ed è
lì che si insedia la fotografia.

Quattro scelte fanno la differenza fra un esperimento e un codice che si legge
davvero con il telefono.

**I pattern funzionali restano intatti.** Finder, separatori, timing, alignment,
format e version info sono riprodotti pixel per pixel. La mappa di quali moduli
siano funzionali è calcolata dalla versione e poi *verificata* contro il simbolo
reale (`qr_layout.verify_layout`): una tabella di alignment sbagliata scriverebbe
l'immagine sopra un pattern di servizio senza alcun sintomo visibile.

**Il dithering è vincolato.** I pixel imposti non vengono sovrascritti a
posteriori: entrano nella diffusione d'errore come quantizzazioni già decise, e
lo scarto che introducono viene distribuito ai vicini. L'immagine si riadatta
attorno al codice invece di subirlo.

**La spinta sul singolo modulo è calcolata, non indovinata.** Il dithering a
diffusione d'errore conserva la luminanza media locale: se la media di un modulo
vale 0,30, ne usciranno circa il 70% di pixel scuri. Non serve quindi tentare —
si risolve per la miscela esatta

```
lum' = lum·(1 − a·w) + t·a·w        con  media(lum') = 0,5 ∓ margine
```

dove `t` è il colore del modulo e `w` un peso a media 1 che concentra la spinta
verso il centro. I moduli già dalla parte giusta della soglia restano intatti:
`a` vale 0 e l'immagine non viene toccata affatto. È il punto che conta di più,
perché il vincolo che decide la lettura non è il pixel centrale ma la *media* del
modulo: appena la foto viene rimpicciolita o sfocata — cioè sempre, con una
fotocamera — è quella media a fare il colore.

**La maschera XOR è scelta guardando la foto.** Delle otto maschere previste
dallo standard si adotta quella la cui trama somiglia già di più all'immagine,
prima ancora di disegnarla. Non costa nulla in leggibilità.

## Il compromesso, misurato

Ogni parametro che irrobustisce il codice toglie qualcosa alla fotografia. Il
programma misura entrambe le cose, così la scelta è un dato e non un'impressione:

- **leggibilità** — il simbolo viene ridecodificato con ZBar e OpenCV attraverso
  dieci condizioni (da 12 a 4 pixel per modulo, con sfocatura e rumore). Le
  condizioni sono espresse in pixel *per modulo*, non in pixel assoluti, perché
  un simbolo a 105 moduli ne richiede il doppio di uno a 57 per essere letto alla
  stessa distanza. Un QR ordinario supera la batteria al 100% a ogni versione:
  il punteggio è quindi confrontabile con un codice normale.
- **fedeltà** — correlazione fra il risultato sfocato e la luminanza voluta.
  L'occhio a distanza media i pixel dell'halftone, e questa metrica fa lo stesso.

Sulla foto di prova, al variare del solo margine:

| margine | fedeltà | leggibilità |
|--------:|--------:|------------:|
| 0,00 | 0,75 | 80% |
| 0,05 | 0,66 | 90% |
| 0,10 | 0,53 | 100% |
| 0,18 | 0,30 | 100% |

I tre profili predefiniti sono i punti notevoli di questa curva:

| profilo | versione minima | margine | soglia | quando |
|---|---|---|---|---|
| `foto` | 20 | 0,00 | 70% | l'immagine conta più di tutto; si scansiona da vicino e a fuoco |
| `equilibrato` *(default)* | 14 | 0,10 | 90% | il ritratto resta riconoscibile e il codice regge sfocatura e rumore |
| `robusto` | 8 | 0,18 | 100% | volantini, insegne, stampe piccole, letture da lontano |

Se la verifica non raggiunge la soglia, i parametri vengono irrigiditi a gradini
— prima il margine, che tocca solo i moduli a rischio, poi il nucleo e la spinta
uniforme, che agiscono su tutta la superficie — e si sceglie il primo che passa.

## Interfaccia grafica

Due interfacce, entrambe in inglese, sopra lo stesso motore.

**Finestra nativa** (`gui.py`, Tkinter) su Windows, macOS e Linux: campo immagine
con selettore di file di sistema, campo testo, tutti i parametri, anteprima,
pulsante **New** per ricominciare e **Save As…** che apre il dialogo di
salvataggio del sistema operativo, dove si sceglie nome e cartella. La
generazione gira in un thread separato: la finestra non si blocca mentre lavora,
e il riquadro sotto l'anteprima riporta versione, moduli, fedeltà e leggibilità.

**Pagina web locale** (`webgui.py`) per iPhone e iPad, dove Tkinter non esiste,
e come ripiego automatico ovunque manchi una sessione grafica — via SSH, nei
container, sui server. Il server ascolta solo su `127.0.0.1`. È pensata mobile
first: una colonna sotto i 900 px, comandi da 48 px, barra delle azioni che
rispetta la safe area, tema chiaro e scuro, nessuno scorrimento orizzontale a
360 e 390 px di larghezza. Il pulsante **Save** chiede il nome, scrive il file
nella cartella scelta all'avvio (`--save-dir`) e lo passa anche al browser, che
su iOS apre il pannello di condivisione.

```bash
./run-gui.sh --web --port 9000        # anche da desktop, se serve
python webgui.py --save-dir ~/Desktop
```

## Uso da riga di comando

```bash
# I tre compromessi
python dithered_qr.py "https://esempio.it" foto.jpg -o qr.png --profile foto
python dithered_qr.py "https://esempio.it" foto.jpg -o qr.png --profile robusto

# Inquadratura: il volto viene cercato da solo, ma si può decidere a mano
python dithered_qr.py "testo" foto.jpg --focus center --center 0.5,0.3 --zoom 1.4

# Colori e resa
python dithered_qr.py "testo" foto.jpg --dark "#12263a" --light "#f4f1de"
python dithered_qr.py "testo" foto.jpg --dither atkinson --clahe 3 --sharpen 1.0

# Per la stampa: lato minimo, ingrandito a fattore intero
python dithered_qr.py "testo" foto.jpg --scale 13 --out-size 2000
```

`python dithered_qr.py --help` elenca tutte le opzioni.

### Esplorare i parametri

`tune.py` genera una griglia di varianti e ne misura leggibilità e fedeltà:

```bash
python tune.py "https://esempio.it" foto.jpg \
    --grid margin=0,0.05,0.1,0.15 min_version=12,16,20 --out-dir varianti
```

## Come scegliere la fotografia

Il codice ha a disposizione poche decine di moduli: il soggetto deve reggere
quella riduzione.

- **Volti grandi e frontali.** L'inquadratura automatica cerca il volto e ci
  stringe sopra; se il ritratto è a figura intera, il viso sparisce.
- **Soggetto e sfondo su luminanze diverse.** Uno sfondo complesso e scuro come
  un bosco notturno si mescola ai capelli e al codice. Un fondo chiaro e liscio
  è quello che rende meglio, ed è il motivo per cui i QR-ritratto che si vedono
  in giro sono quasi sempre su fondo bianco.
- **Contrasto locale, non globale.** Il CLAHE predefinito separa già le fasce di
  luminanza; `--clahe 0` lo disattiva se l'immagine è già incisa.

## Verificare prima di stampare

Il punteggio riportato è una simulazione, non una promessa: prima di mandare in
stampa **provate il codice con il vostro telefono**, alla distanza e con
l'illuminazione d'uso reale. Il profilo `foto` in particolare rinuncia di
proposito alle condizioni difficili.

Se un simbolo non si legge:

1. `--profile robusto`, oppure `--margin 0.2`;
2. `--min-version` più basso: meno moduli, ciascuno più grande;
3. `--core 5` (con `--scale 9`) per un nucleo più marcato;
4. stampare più grande — la maggior parte dei fallimenti è risoluzione, non algoritmo.

## Struttura

| file | contenuto |
|---|---|
| `dithered_qr.py` | pipeline e riga di comando |
| `gui.py` | finestra nativa (Tkinter), dialoghi di sistema |
| `webgui.py` | interfaccia web locale, mobile first, per iOS e sessioni senza schermo |
| `qr_layout.py` | geometria del simbolo e verifica della mappa dei moduli funzionali |
| `dither.py` | dithering a diffusione d'errore con pixel vincolati (6 kernel + Bayer) |
| `framing.py` | ritaglio quadrato con ricerca del volto |
| `imaging.py` | operazioni sulle immagini, con OpenCV o in puro numpy/Pillow |
| `verify.py` | ridecodifica in condizioni degradate, metrica di fedeltà |
| `tune.py` | griglia di parametri con misura del compromesso |
| `test_dithered_qr.py` | test (`pytest -q`) |
| `install.ps1`, `install.sh`, `install-ios.sh` | installazione per piattaforma |
| `run-gui.ps1`, `run-gui.sh`, `run-gui-ios.sh` | apertura dell'interfaccia per piattaforma |

## Requisiti

Indispensabili `segno`, `Pillow` e `numpy` — tutto il resto è facoltativo.
`opencv-python` (serie 4) aggiunge un secondo decoder, il rilevamento del volto
e un po' di velocità; `pyzbar` aggiunge ZBar, il decoder più severo dei due.

Senza OpenCV il generatore funziona per intero: sfocatura, ridimensionamento,
equalizzazione e contrasto locale hanno un'implementazione in numpy che i test
confrontano con quella di OpenCV. Quello che si perde è l'inquadratura
automatica sul volto e, se manca anche ZBar, la verifica di leggibilità — che
viene **saltata dichiarandolo**, non data per fallita. È la differenza che conta:
un punteggio nullo verrebbe scambiato per un codice illeggibile e manderebbe la
taratura automatica a irrigidire i parametri, rovinando l'immagine per un
problema che non esiste.

Questa è la configurazione di iOS, dove le estensioni native non sono
installabili: vedi [INSTALL.md](INSTALL.md).

## Limiti noti

- **La quiet zone bianca serve.** `--quiet-zone image` estende la foto fino al
  bordo, ma sulla foto di prova la lettura scende dal 100% al 70%.
- **Il budget di correzione d'errore non è spendibile a piacere.** L'opzione
  `--sacrifice` lascia all'immagine i moduli più contesi, contando sull'ECC:
  in pratica rende poco, perché un solo modulo sbagliato corrompe un codeword
  intero da otto, e gli errori sparsi ne bruciano uno ciascuno. Sfruttarlo
  davvero richiederebbe di sacrificare codeword interi, cioè la mappa
  modulo→codeword con l'interlacciamento dei blocchi. Predefinita a 0.
- **I byte di riempimento sono sprecati.** Con un URL corto in versione 20 la
  maggior parte dei codeword è padding, e il loro valore è arbitrario: sceglierli
  in modo che i moduli somiglino alla foto (la tecnica dei *QArt code*)
  aumenterebbe molto la fedeltà a parità di leggibilità. Richiede un encoder QR
  proprio, con Reed–Solomon, al posto di `segno`.
