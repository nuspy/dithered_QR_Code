"""Genera un QR code "dithered": un ritratto in halftone che resta scansionabile.

Idea di fondo
-------------
Uno scanner QR non guarda l'intero modulo: ricostruisce la griglia dai pattern
di servizio e poi campiona il *centro* di ogni modulo. Se ogni modulo viene
disegnato come un blocco di `scale` x `scale` pixel e si vincola solo il nucleo
centrale di `core` x `core`, restano liberi circa 1 - (core/scale)^2 dei pixel:
con i valori di default e' l'89%, abbastanza per far vivere un'immagine
in dithering dentro al codice.

Tre accorgimenti fanno la differenza fra un esperimento e un QR che si legge
davvero con il telefono:

1. i pattern funzionali (finder, timing, alignment, format info) sono riprodotti
   per intero, non a nuclei;
2. il dithering e' *vincolato*: l'errore introdotto dai nuclei imposti viene
   diffuso ai pixel vicini, cosi' l'immagine si riadatta attorno al codice;
3. la maschera XOR del simbolo (0-7) viene scelta fra le otto possibili come
   quella che gia' somiglia di piu' alla foto, prima ancora di disegnarla.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import segno
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

import framing
import imaging
import verify
from dither import METHODS, dither
from framing import square_crop
from qr_layout import function_masks, verify_layout

ERROR_LEVELS = ("L", "M", "Q", "H")

# Sovraccarico applicato alla media di modulo oltre il margine richiesto.
MEAN_SLACK = 0.05

# Preset ricavati misurando fedelta' e leggibilita' su una griglia di parametri
# (vedi tune.py). Il margine e' la manopola principale del compromesso; la
# versione decide quanto e' fine la griglia su cui l'immagine viene approssimata.
PROFILES: dict[str, dict] = {
    # Immagine al primo posto. Accetta di proposito una soglia di lettura piu'
    # bassa: il codice si legge da vicino e a fuoco, non da lontano. E' il
    # compromesso dei QR "artistici" che si vedono in giro, qui pero' misurato
    # e dichiarato invece che subito.
    "foto": dict(min_version=20, margin=0.0, target=0.7),
    # Compromesso: la foto resta riconoscibile e la lettura regge tutta la
    # batteria di prova, sfocatura e rumore compresi.
    "equilibrato": dict(min_version=14, margin=0.10, target=0.9),
    # Lettura al primo posto: pochi moduli, grandi e ben marcati.
    "robusto": dict(min_version=8, margin=0.18, target=1.0),
}


@dataclass
class Settings:
    """Parametri di resa. `core` e `blend` sono quelli che l'auto-tuning muove."""

    scale: int = 9
    core: int | None = None        # None = circa un terzo di scale
    blend: float = 0.0             # spinta minima uniforme, di norma non serve
    margin: float = 0.10           # scarto di maggioranza richiesto in ogni modulo
    sacrifice: float = 0.0         # quota di moduli lasciati all'immagine (vedi CLI)
    center_pull: float = 0.35      # quanto si preferisce correggere vicino al centro
    passes: int = 3                # iterazioni del bias adattivo
    error: str = "H"
    version: int | None = None
    min_version: int = 14          # piu' moduli = griglia piu' fine per la foto
    border: int = 4
    quiet: str = "white"           # "white" | "image"
    method: str = "floyd-steinberg"
    fit: str = "cover"             # "cover" | "contain"
    focus: str = "face"            # "face" | "center"
    center: tuple[float, float] = (0.5, 0.42)
    zoom: float = 1.0
    contrast: float = 1.15
    brightness: float = 1.0
    gamma: float = 1.0
    autocontrast: bool = True
    clahe: float = 2.0             # contrasto locale adattivo; 0 lo disattiva
    sharpen: float = 0.6           # nitidezza prima del dithering
    soft_function: bool = False    # timing/alignment a nuclei invece che pieni
    mask: int | None = None        # None = scelta automatica
    dark: str = "#000000"
    light: str = "#ffffff"
    out_size: int | None = None


@dataclass
class Result:
    image: Image.Image
    settings: Settings
    version: int
    mask: int
    modules: int
    free_ratio: float
    corrected: int = 0
    fidelity: float = 0.0
    report: verify.Report | None = None


# --------------------------------------------------------------------------
# simbolo QR
# --------------------------------------------------------------------------

def _matrix(qr: segno.QRCode) -> np.ndarray:
    return np.array([list(row) for row in qr.matrix], dtype=bool)


def resolve(cfg: Settings) -> Settings:
    """Riempie i parametri lasciati automatici e valida quelli incompatibili."""
    if cfg.scale % 2 == 0 or cfg.scale < 3:
        raise ValueError("scale deve essere dispari e >= 3")
    core = cfg.core
    if core is None:
        # Un terzo del lato e' il compromesso classico dell'halftone QR: il
        # nucleo resta ben visibile allo scanner e cede all'immagine l'89%
        # dell'area del modulo.
        core = max(1, round(cfg.scale / 3))
        core += 1 - core % 2
    if core % 2 == 0 or not 1 <= core <= cfg.scale:
        raise ValueError("core deve essere dispari e compreso fra 1 e scale")
    if not 0.0 <= cfg.blend <= 1.0:
        raise ValueError("blend deve stare fra 0 e 1")
    if cfg.border < 0:
        raise ValueError("border non puo' essere negativo")
    return replace(cfg, core=core)


def choose_version(payload: str, cfg: Settings) -> int:
    """Versione da usare: quella richiesta, altrimenti la minima alzata a min_version.

    Alzare la versione allarga la tela (piu' moduli, piu' dettaglio) al prezzo di
    moduli piu' piccoli; i dati mancanti vengono riempiti da segno con padding.
    """
    if cfg.version is not None:
        return cfg.version
    natural = int(segno.make(payload, error=cfg.error, micro=False, boost_error=False).version)
    return max(natural, min(cfg.min_version, 40))


def _module_targets(lum: np.ndarray, modules: int, scale: int) -> np.ndarray:
    """Luminanza media per modulo, usata per scegliere la maschera XOR."""
    block = lum[: modules * scale, : modules * scale]
    return block.reshape(modules, scale, modules, scale).mean(axis=(1, 3))


def build_symbol(
    payload: str, cfg: Settings, target: np.ndarray | None = None
) -> tuple[np.ndarray, int, int]:
    """Costruisce il simbolo, scegliendo la maschera che meglio approssima la foto.

    Restituisce (matrice, versione, maschera).
    """
    base = dict(error=cfg.error, version=choose_version(payload, cfg),
                micro=False, boost_error=False)
    masks = [cfg.mask] if cfg.mask is not None else list(range(8))

    best: tuple[float, np.ndarray, int, int] | None = None
    for mask in masks:
        qr = segno.make(payload, mask=mask, **base)
        matrix = _matrix(qr)
        version = int(qr.version)
        verify_layout(matrix, version)
        if target is None or len(masks) == 1:
            return matrix, version, mask

        size = matrix.shape[0]
        hard, soft = function_masks(version, size)
        free = ~(hard | soft)
        want_dark = target[:size, :size] < 0.5
        score = float((matrix[free] == want_dark[free]).mean())
        if best is None or score > best[0]:
            best = (score, matrix, version, mask)

    assert best is not None
    return best[1], best[2], best[3]


# --------------------------------------------------------------------------
# immagine
# --------------------------------------------------------------------------

def load_luminance(path: Path, side: int, cfg: Settings, warn=None) -> np.ndarray:
    """Carica l'immagine come luminanza float in [0, 1], 0 = nero."""
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        flat = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(flat, img)
    img = img.convert("L")

    if cfg.fit == "cover":
        img = square_crop(img, focus=cfg.focus, center=cfg.center, zoom=cfg.zoom, warn=warn)
        img = img.resize((side, side), Image.LANCZOS)
    else:
        img = ImageOps.contain(img, (side, side), method=Image.LANCZOS)
        canvas = Image.new("L", (side, side), 255)
        canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
        img = canvas

    if cfg.clahe > 0:
        # Il dithering ha un solo bit per pixel: se il soggetto e lo sfondo
        # stanno nella stessa fascia di luminanza, si fondono. Il contrasto
        # locale li separa senza bruciare le alte luci.
        img = Image.fromarray(imaging.clahe(np.asarray(img, dtype=np.uint8), cfg.clahe, tiles=8))
    if cfg.autocontrast:
        img = ImageOps.autocontrast(img, cutoff=1)
    if cfg.brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(cfg.brightness)
    if cfg.contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(cfg.contrast)
    if cfg.sharpen > 0:
        # Il rimpicciolimento a poche decine di moduli spegne i bordi: qui si
        # recuperano, perche' nel dithering contano piu' delle mezzetinte.
        blurred = img.filter(ImageFilter.GaussianBlur(radius=max(1.0, side / 220)))
        img = Image.blend(blurred, img, 1.0 + cfg.sharpen)

    lum = np.asarray(img, dtype=np.float64) / 255.0
    if cfg.gamma != 1.0:
        lum = np.clip(lum, 0.0, 1.0) ** (1.0 / cfg.gamma)
    return np.clip(lum, 0.0, 1.0)


# --------------------------------------------------------------------------
# composizione
# --------------------------------------------------------------------------

def _core_slice(scale: int, core: int) -> slice:
    start = (scale - core) // 2
    return slice(start, start + core)


def _falloff(scale: int) -> np.ndarray:
    """Peso decrescente dal centro al bordo del modulo, fra 1 e circa 0."""
    axis = np.abs(np.arange(scale) - (scale - 1) / 2.0)
    cheb = np.maximum(axis[:, None], axis[None, :])
    return np.clip(1.0 - cheb / (scale / 2.0 + 0.5), 0.0, 1.0)


def _weight(scale: int, pull: float) -> np.ndarray:
    """Peso della spinta dentro il modulo, normalizzato a media 1.

    Media 1 e' cio' che rende esatto il calcolo della miscela: la media del
    modulo si sposta esattamente di quanto previsto. `pull` decide quanto la
    spinta preferisce il centro; piu' e' alta, meno spinta massima e' possibile
    prima che i pixel centrali saturino.
    """
    if scale == 1:
        return np.ones((1, 1))
    axis = np.abs(np.arange(scale) - (scale - 1) / 2.0)
    cheb = np.maximum(axis[:, None], axis[None, :])
    w = 1.0 - np.clip(pull, 0.0, 0.9) * (cheb / cheb.max())
    return w / w.mean()


def function_map(matrix: np.ndarray, version: int, cfg: Settings) -> np.ndarray:
    """Moduli da riprodurre pieni, pixel per pixel."""
    hard, soft = function_masks(version, matrix.shape[0])
    return hard if cfg.soft_function else (hard | soft)


def compose(
    matrix: np.ndarray,
    version: int,
    lum: np.ndarray,
    cfg: Settings,
    extra: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Prepara la luminanza corretta e la mappa dei pixel vincolati.

    Il punto di appoggio e' una proprieta' del dithering a diffusione d'errore:
    conserva la luminanza media locale. Se la media di un modulo vale 0,30, il
    dithering ci mettera' circa il 70% di pixel scuri. Quindi non serve indovinare
    quanta spinta dare: si calcola la miscela esatta

        lum' = lum (1 - a w) + t a w        con  media(lum') = 0,5 -/+ margine

    dove `t` e' il colore del modulo e `w` un peso che concentra la spinta verso
    il centro (normalizzato a media 1, cosi' il conto della media resta valido).
    I moduli gia' dalla parte giusta non vengono toccati affatto: `a` vale 0 e
    l'immagine resta esattamente com'era.

    `extra` e' una spinta aggiuntiva per modulo, usata dal ciclo adattivo per i
    moduli che il dithering non ha convinto al primo giro. Restituisce
    (luminanza, vincoli, frazione di pixel liberi); i vincoli valgono -1 (libero),
    0 (scuro imposto) o 1 (chiaro imposto).
    """
    size = matrix.shape[0]
    scale, core = cfg.scale, cfg.core
    offset = 0 if cfg.quiet == "white" else cfg.border
    side = lum.shape[0]
    span = slice(offset * scale, (offset + size) * scale)

    full = function_map(matrix, version, cfg)
    ones = np.ones((scale, scale))

    weight = _weight(scale, cfg.center_pull)
    w_tile = np.tile(weight, (size, size))
    a_max = 1.0 / weight.max()                 # oltre, i pixel centrali saturano

    inner = lum[span, span]
    blocks = inner.reshape(size, scale, size, scale)
    mean_lum = blocks.mean(axis=(1, 3))                       # media per modulo
    mean_wlum = (blocks * weight[None, :, None, :]).mean(axis=(1, 3))

    t = np.where(matrix, 0.0, 1.0)                            # colore del modulo
    # Puntare la media esatta sulla soglia significa atterrarci sopra una volta
    # su due: il dithering conserva la media, non la garantisce pixel per pixel.
    # Un piccolo sovraccarico mette il conteggio al riparo dalle fluttuazioni.
    goal_margin = cfg.margin + MEAN_SLACK
    if extra is not None:
        goal_margin = goal_margin + extra      # il ciclo adattivo alza l'asticella
    goal_margin = np.clip(goal_margin, 0.0, 0.48)
    goal = np.where(matrix, 0.5 - goal_margin, 0.5 + goal_margin)

    off_target = np.where(matrix, mean_lum > goal, mean_lum < goal)

    # Il livello di correzione d'errore e' un budget da spendere, non una riserva
    # da custodire: con ECC H un terzo dei codeword puo' essere illeggibile e il
    # simbolo si decodifica lo stesso. Conviene allora lasciare all'immagine i
    # moduli dove imporre la maggioranza costerebbe di piu' - i bordi netti, le
    # alte luci, le ombre piene - e imporla su tutti gli altri. Li' resta il solo
    # nucleo centrale, che allo scanner ravvicinato basta comunque.
    sacrificed = np.zeros_like(matrix, dtype=bool)
    data = ~full
    budget = int(cfg.sacrifice * data.sum())
    if budget > 0:
        cost = np.where(data & off_target, np.abs(mean_lum - goal), -1.0)
        ranked = np.argsort(cost, axis=None)[::-1][:budget]
        picked = ranked[cost.ravel()[ranked] > 0]
        sacrificed.ravel()[picked] = True

    # Prima spinta, modellata sul centro: a = (media - obiettivo)/(media pesata - t).
    denom = mean_wlum - t
    with np.errstate(divide="ignore", invalid="ignore"):
        a1 = np.where(np.abs(denom) > 1e-9, (mean_lum - goal) / denom, 0.0)
    a1 = np.where(off_target & ~sacrificed, a1, 0.0)
    a1 = np.clip(np.maximum(a1, cfg.blend), 0.0, a_max)
    a1[full] = a_max

    target = np.kron(t, ones)
    bias1 = np.kron(a1, ones) * w_tile
    stage1 = inner * (1.0 - bias1) + target * bias1

    # Seconda spinta, uniforme: chiude il residuo dei moduli che la prima non ha
    # potuto raggiungere senza saturare. Essendo piatta, arriva sempre a bersaglio.
    mean1 = stage1.reshape(size, scale, size, scale).mean(axis=(1, 3))
    denom2 = mean1 - t
    with np.errstate(divide="ignore", invalid="ignore"):
        a2 = np.where(np.abs(denom2) > 1e-9, (mean1 - goal) / denom2, 0.0)
    still_off = np.where(matrix, mean1 > goal, mean1 < goal)
    a2 = np.where(still_off & ~sacrificed, np.clip(a2, 0.0, 1.0), 0.0)
    a2[full] = 1.0                                            # moduli funzionali: pieni

    bias2 = np.kron(a2, ones)
    out = stage1 * (1.0 - bias2) + target * bias2

    canvas = lum.copy()
    canvas[span, span] = np.clip(out, 0.0, 1.0)

    # Vincoli: modulo funzionale tutto imposto, modulo dati solo nel nucleo.
    core_mask = np.zeros((scale, scale), dtype=bool)
    csl = _core_slice(scale, core)
    core_mask[csl, csl] = True
    pinned = np.kron(full, ones).astype(bool) | np.tile(core_mask, (size, size))
    value = np.kron(t, ones).astype(np.int8)

    forced = np.full((side, side), -1, dtype=np.int8)
    forced[span, span] = np.where(pinned, value, -1)

    free = float((forced < 0).mean())
    return canvas, forced, free, sacrificed


def module_deficit(
    dark_px: np.ndarray, matrix: np.ndarray, skip: np.ndarray, cfg: Settings
) -> np.ndarray:
    """Quanto manca a ogni modulo dati per essere in maggioranza, in frazione d'area.

    `skip` azzera i moduli su cui non si vuole intervenire: quelli funzionali,
    gia' pieni, e quelli lasciati di proposito all'immagine.
    """
    size = matrix.shape[0]
    scale = cfg.scale
    offset = 0 if cfg.quiet == "white" else cfg.border
    total = scale * scale
    need = int(np.ceil(total * (0.5 + cfg.margin)))

    sym = dark_px[
        offset * scale : (offset + size) * scale,
        offset * scale : (offset + size) * scale,
    ]
    counts = sym.reshape(size, scale, size, scale).sum(axis=(1, 3))
    have = np.where(matrix, counts, total - counts)
    deficit = np.maximum(0, need - have) / total
    deficit[skip] = 0.0
    return deficit


def enforce_majority(
    dark_px: np.ndarray,
    matrix: np.ndarray,
    skip: np.ndarray,
    lum: np.ndarray,
    cfg: Settings,
) -> int:
    """Impone che ogni modulo sia in maggioranza del proprio colore.

    Il nucleo centrale basta finche' lo scanner campiona un punto solo. Appena
    l'immagine viene rimpicciolita o sfocata - cioe' sempre, con una fotocamera -
    il modulo vale la *media* dei suoi pixel, e con un nucleo di 3x3 su 9x9 quella
    media la decide l'immagine, non il codice.

    Qui si conta quanti pixel scuri ha ogni modulo dati e, se non e' dalla parte
    giusta della soglia, si ribaltano i pixel meno costosi: quelli che nella foto
    erano gia' quasi del colore richiesto, preferendo i piu' vicini al centro
    perche' sopravvivono meglio alla sfocatura. `skip` esclude i moduli gia'
    pieni e quelli lasciati di proposito all'immagine. Restituisce i corretti.
    """
    size = matrix.shape[0]
    scale = cfg.scale
    offset = 0 if cfg.quiet == "white" else cfg.border
    total = scale * scale
    need = int(np.ceil(total * (0.5 + cfg.margin)))
    bonus = _falloff(scale) * cfg.center_pull

    fixed = 0
    for r in range(size):
        y0 = (r + offset) * scale
        for c in range(size):
            if skip[r, c]:
                continue
            x0 = (c + offset) * scale
            block = dark_px[y0 : y0 + scale, x0 : x0 + scale]
            want_dark = bool(matrix[r, c])
            have = int(block.sum()) if want_dark else total - int(block.sum())
            if have >= need:
                continue

            target = lum[y0 : y0 + scale, x0 : x0 + scale]
            if want_dark:
                candidates = ~block                 # pixel chiari da scurire
                cost = target - bonus               # scurire un pixel gia' scuro costa poco
            else:
                candidates = block                  # pixel scuri da schiarire
                cost = (1.0 - target) - bonus

            idx = np.flatnonzero(candidates.ravel())
            if idx.size == 0:
                continue
            order = idx[np.argsort(cost.ravel()[idx], kind="stable")][: need - have]
            rows, cols = np.unravel_index(order, (scale, scale))
            dark_px[y0 + rows, x0 + cols] = want_dark
            fixed += 1
    return fixed


def _hex(color: str) -> tuple[int, int, int]:
    s = color.lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise ValueError(f"colore non valido: {color}")
    return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def render(dark_px: np.ndarray, cfg: Settings) -> Image.Image:
    dark_rgb, light_rgb = _hex(cfg.dark), _hex(cfg.light)
    rgb = np.where(dark_px[:, :, None], np.array(dark_rgb), np.array(light_rgb)).astype(np.uint8)
    img = Image.fromarray(rgb, mode="RGB")

    if cfg.quiet == "white":
        pad = cfg.border * cfg.scale
        img = ImageOps.expand(img, border=pad, fill=light_rgb)

    if cfg.out_size and cfg.out_size > img.width:
        # Solo ingrandimenti a fattore intero: un fattore frazionario darebbe
        # moduli di larghezza disuguale (9 px uno, 10 px il successivo) e basta
        # quello per far perdere la griglia allo scanner. NEAREST perche' i
        # pixel dell'halftone devono restare netti, non interpolati.
        factor = -(-cfg.out_size // img.width)          # arrotonda per eccesso
        img = img.resize((img.width * factor, img.height * factor), Image.NEAREST)
    return img


# --------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------

def generate(payload: str, image_path: Path, cfg: Settings, warn=None) -> Result:
    cfg = resolve(cfg)

    # Primo giro solo per conoscere la dimensione del simbolo, poi si rilegge
    # l'immagine alla risoluzione giusta e si sceglie la maschera migliore.
    probe, version, _ = build_symbol(payload, replace(cfg, mask=cfg.mask or 0))
    size = probe.shape[0]
    # Con quiet zone bianca la tela di lavoro e' il solo simbolo e il bordo si
    # aggiunge dopo; con quiet zone "image" l'immagine ci scorre dentro.
    work_modules = size + (2 * cfg.border if cfg.quiet == "image" else 0)
    side = work_modules * cfg.scale

    lum = load_luminance(image_path, side, cfg, warn=warn)
    offset = 0 if cfg.quiet == "white" else cfg.border
    inner = lum[
        offset * cfg.scale : (offset + size) * cfg.scale,
        offset * cfg.scale : (offset + size) * cfg.scale,
    ]
    targets = _module_targets(inner, size, cfg.scale)

    matrix, version, mask = build_symbol(payload, cfg, target=targets)
    full = function_map(matrix, version, cfg)

    # Ciclo adattivo: si ridisegna insistendo solo sui moduli rimasti in
    # minoranza. Spingere solo dove serve costa all'immagine molto meno che
    # alzare il bias ovunque, e il dithering continua a diffondere l'errore.
    extra = np.zeros(matrix.shape, dtype=np.float64)
    dark_px = free = None
    skip = full
    for _ in range(max(1, cfg.passes)):
        lum2, forced, free, sacrificed = compose(matrix, version, lum, cfg, extra)
        skip = full | sacrificed
        dark_px = dither(lum2, forced, method=cfg.method)
        if cfg.margin <= 0:
            break
        deficit = module_deficit(dark_px, matrix, skip, cfg)
        if not deficit.any():
            break
        extra += np.where(deficit > 0, np.clip(deficit * 1.5, 0.03, 0.20), 0.0)

    # Rete di sicurezza: i pochi moduli che il ciclo non ha convinto vengono
    # sistemati a mano, ribaltando i pixel meno costosi per l'immagine.
    corrected = enforce_majority(dark_px, matrix, skip, lum, cfg) if cfg.margin > 0 else 0
    img = render(dark_px, cfg)
    score = verify.fidelity(dark_px, lum, cfg.scale)

    return Result(
        image=img,
        settings=cfg,
        version=version,
        mask=mask,
        modules=size + 2 * cfg.border,
        free_ratio=free,
        corrected=corrected,
        fidelity=score,
    )


def _fallback_ladder(cfg: Settings) -> list[Settings]:
    """Gradini di irrigidimento, dal meno al piu' invasivo per l'immagine.

    Prima si alza il margine di maggioranza, che tocca solo i moduli davvero a
    rischio; poi il nucleo e il bias, che agiscono su tutta la superficie.
    """
    cfg = resolve(cfg)
    ladder = [cfg]

    # Primo: si restituisce al codice qualche modulo dei piu' contesi. Costa
    # poco all'immagine perche' sono pochi, anche se sono i piu' visibili.
    for sacrifice in (0.06, 0.0):
        if sacrifice < cfg.sacrifice:
            ladder.append(replace(cfg, sacrifice=sacrifice))

    # Poi il margine, a passi piccoli: ogni centesimo in piu' e' contrasto
    # tolto alla foto, quindi conviene fermarsi al primo valore che funziona.
    for step in (0.04, 0.08, 0.12, 0.18, 0.24):
        margin = round(cfg.margin + step, 3)
        if margin <= 0.45:
            ladder.append(replace(ladder[-1], margin=margin))

    stiff = replace(ladder[-1])
    core, blend = stiff.core, stiff.blend
    while core < cfg.scale:
        core = min(core + 2, cfg.scale)
        blend = min(blend + 0.15, 0.9)
        ladder.append(replace(stiff, core=core, blend=blend))
    return ladder


def generate_verified(
    payload: str,
    image_path: Path,
    cfg: Settings,
    target_score: float = 0.9,
    auto: bool = True,
    quiet: bool = False,
    warn=None,
) -> Result:
    """Genera e verifica; se serve, irrigidisce i parametri finche' il QR si legge."""
    if not verify.available():
        # Senza decoder non si puo' misurare nulla. Insistere significherebbe
        # scambiare "non misurabile" per "illeggibile" e irrigidire i parametri
        # fino a rovinare l'immagine per un problema inesistente.
        if not quiet:
            print("  nessun decoder QR installato: verifica saltata", file=sys.stderr)
        return generate(payload, image_path, cfg, warn=warn)

    attempts = _fallback_ladder(cfg) if auto else [cfg]
    best: Result | None = None

    for i, attempt in enumerate(attempts, 1):
        # Gli avvisi sull'immagine valgono per tutti i tentativi: si danno una
        # volta sola, al primo, per non ripeterli a ogni gradino.
        result = generate(payload, image_path, attempt, warn=warn if i == 1 else None)
        result.report = verify.check(result.image, payload, result.modules)
        if not quiet:
            print(
                f"  tentativo {i}/{len(attempts)}  core={result.settings.core}/{attempt.scale} "
                f"margine={attempt.margin:.2f} blend={attempt.blend:.2f}"
                f"  ->  {result.report.score:.0%} ({result.corrected} moduli corretti)",
                file=sys.stderr,
            )
        if best is None or result.report.score > best.report.score:  # type: ignore[union-attr]
            best = result
        if result.report.score >= target_score:
            return result

    assert best is not None
    return best


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dithered_qr",
        description="Genera un QR code scansionabile in cui e' immersa un'immagine in dithering.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("text", help="testo o URL codificato nel QR")
    p.add_argument("image", type=Path, help="immagine sorgente")
    p.add_argument("-o", "--out", type=Path, default=Path("qr.png"), help="file PNG di uscita")
    p.add_argument("--profile", choices=tuple(PROFILES), default="equilibrato",
                   help="compromesso fra resa dell'immagine e facilita' di lettura")

    g = p.add_argument_group("struttura del codice")
    g.add_argument("--error", choices=ERROR_LEVELS, default="H", help="livello di correzione errori")
    g.add_argument("--version", type=int, choices=range(1, 41), metavar="1-40",
                   help="versione QR forzata (default: minima che contiene il testo)")
    g.add_argument("--min-version", type=int, choices=range(1, 41), metavar="1-40",
                   help="versione minima: piu' moduli danno piu' dettaglio, ma vanno inquadrati "
                        "da vicino (default dal profilo)")
    g.add_argument("--mask", type=int, choices=range(8), metavar="0-7",
                   help="maschera XOR forzata (default: quella piu' simile all'immagine)")
    g.add_argument("--border", type=int, default=4, help="moduli di quiet zone")
    g.add_argument("--quiet-zone", dest="quiet", choices=("white", "image"), default="white",
                   help="quiet zone bianca oppure occupata dall'immagine")

    g = p.add_argument_group("resa")
    g.add_argument("--scale", type=int, default=9, help="pixel per modulo (dispari)")
    g.add_argument("--core", type=int, help="lato del nucleo vincolato, dispari (default: scale/3)")
    g.add_argument("--blend", type=float, default=0.0,
                   help="spinta minima uniforme verso il colore del modulo (0-1)")
    g.add_argument("--margin", type=float,
                   help="scarto di maggioranza imposto in ogni modulo, 0 lo disattiva "
                        "(default dal profilo)")
    g.add_argument("--sacrifice", type=float, default=0.0,
                   help="quota di moduli lasciata all'immagine: sperimentale, un modulo sbagliato "
                        "brucia un codeword intero, quindi alzarla degrada in fretta la lettura")
    g.add_argument("--passes", type=int, default=3, help="iterazioni del bias adattivo")
    g.add_argument("--center-pull", type=float, default=0.35,
                   help="quanto le correzioni si concentrano al centro del modulo")
    g.add_argument("--dither", dest="method", choices=METHODS, default="floyd-steinberg")
    g.add_argument("--fit", choices=("cover", "contain"), default="cover")
    g.add_argument("--focus", choices=("face", "center"), default="face",
                   help="inquadratura: sul volto rilevato oppure sul punto indicato da --center")
    g.add_argument("--center", default="0.5,0.42", metavar="X,Y",
                   help="centro del ritaglio in frazioni di larghezza/altezza")
    g.add_argument("--zoom", type=float, default=1.0, help="ingrandimento del ritaglio")
    g.add_argument("--soft-function", action="store_true",
                   help="disegna timing e alignment a nuclei invece che pieni (piu' bello, meno robusto)")
    g.add_argument("--out-size", type=int,
                   help="lato minimo in pixel: si ingrandisce di un fattore intero fino a "
                        "raggiungerlo (i moduli devono restare tutti larghi uguale)")

    g = p.add_argument_group("immagine")
    g.add_argument("--contrast", type=float, default=1.15)
    g.add_argument("--brightness", type=float, default=1.0)
    g.add_argument("--gamma", type=float, default=1.0)
    g.add_argument("--clahe", type=float, default=2.0,
                   help="contrasto locale adattivo (0 = disattivato)")
    g.add_argument("--sharpen", type=float, default=0.6, help="nitidezza (0 = disattivata)")
    g.add_argument("--no-autocontrast", dest="autocontrast", action="store_false")
    g.add_argument("--dark", default="#000000", help="colore dei pixel scuri")
    g.add_argument("--light", default="#ffffff", help="colore dei pixel chiari")

    g = p.add_argument_group("verifica")
    g.add_argument("--no-auto", dest="auto", action="store_false",
                   help="non irrigidire i parametri se la lettura fallisce")
    g.add_argument("--target", type=float,
                   help="quota di prove di lettura da superare, 0-1 (default dal profilo)")
    g.add_argument("--no-verify", dest="do_verify", action="store_false",
                   help="salta del tutto la verifica di leggibilita'")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.image.exists():
        print(f"immagine non trovata: {args.image}", file=sys.stderr)
        return 2

    try:
        cx, cy = (float(v) for v in args.center.split(","))
    except ValueError:
        print(f"--center non valido: {args.center} (atteso X,Y)", file=sys.stderr)
        return 2

    # I flag espliciti hanno la precedenza sul profilo; quelli lasciati stare
    # (argparse li porta a None) prendono il valore del preset.
    preset = PROFILES[args.profile]
    margin = args.margin if args.margin is not None else preset["margin"]
    min_version = args.min_version if args.min_version is not None else preset["min_version"]
    target = args.target if args.target is not None else preset["target"]

    cfg = Settings(
        scale=args.scale, core=args.core, blend=args.blend,
        margin=margin, sacrifice=args.sacrifice,
        center_pull=args.center_pull, passes=args.passes,
        error=args.error,
        version=args.version, min_version=min_version,
        border=args.border, quiet=args.quiet, method=args.method,
        fit=args.fit, focus=args.focus, center=(cx, cy), zoom=args.zoom,
        contrast=args.contrast, brightness=args.brightness, gamma=args.gamma,
        clahe=args.clahe, sharpen=args.sharpen,
        autocontrast=args.autocontrast, soft_function=args.soft_function, mask=args.mask,
        dark=args.dark, light=args.light, out_size=args.out_size,
    )

    avvisi = {
        framing.FACE_DETECTION_UNAVAILABLE:
            "rilevamento del volto non disponibile (serve OpenCV 4.x): ritaglio centrato, "
            "regolabile con --center e --zoom",
        framing.NO_FACE_FOUND:
            "nessun volto rilevato: ritaglio centrato, regolabile con --center e --zoom",
    }

    def warn(code: str) -> None:
        print(f"  avviso: {avvisi.get(code, code)}", file=sys.stderr)

    try:
        if args.do_verify:
            result = generate_verified(args.text, args.image, cfg,
                                       target_score=target, auto=args.auto, warn=warn)
        else:
            result = generate(args.text, args.image, cfg, warn=warn)
    except ValueError as exc:
        print(f"errore: {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    result.image.save(args.out)

    print(f"scritto {args.out}  ({result.image.width}x{result.image.height} px)")
    print(f"  versione {result.version}, maschera {result.mask}, correzione {result.settings.error}")
    print(f"  {result.modules} moduli, {result.settings.core}/{result.settings.scale} px vincolati "
          f"-> {result.free_ratio:.0%} dei pixel liberi per l'immagine")
    print(f"  fedelta' all'immagine {result.fidelity:.3f} (margine {result.settings.margin:.2f})")
    if result.report is None and args.do_verify:
        print("  leggibilita' non verificata: nessun decoder QR disponibile.")
        print("  installa pyzbar oppure opencv-python, e in ogni caso prova il codice col telefono.")
    if result.report:
        print("  " + str(result.report))
        if result.report.score < target:
            print("  ATTENZIONE: sotto la soglia richiesta; prova --core piu' alto o --blend piu' forte",
                  file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
