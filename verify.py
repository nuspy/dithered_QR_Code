"""Verifica di leggibilita': il QR generato viene riletto in condizioni realistiche.

Un halftone QR che si decodifica sul file PNG a piena risoluzione puo' comunque
fallire sotto la fotocamera di un telefono, dove intervengono rimpicciolimento,
sfocatura e rumore. Qui il simbolo viene ridecodificato attraverso una batteria
di degradazioni e si misura la frazione di casi superati.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import imaging

# Ripubblicati per comodita' di chi importa questo modulo.
HAS_ZBAR = imaging.HAS_ZBAR
decode = imaging.decode_qr


@dataclass
class Report:
    payload: str
    passed: int = 0
    total: int = 0
    failures: list[str] = field(default_factory=list)
    decoders: set[str] = field(default_factory=set)

    @property
    def score(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def __str__(self) -> str:
        engines = "+".join(sorted(self.decoders)) if self.decoders else "nessuno"
        line = f"leggibilita' {self.score:6.1%}  ({self.passed}/{self.total} prove, decoder: {engines})"
        if self.failures:
            line += "\n  falliti: " + ", ".join(self.failures)
        return line


def available() -> bool:
    """Vero se almeno un decoder QR e' installato.

    Senza decoder la verifica non e' possibile, e va detto invece che
    restituire zero: un punteggio nullo verrebbe scambiato per un codice
    illeggibile e manderebbe la taratura automatica a irrigidire i parametri
    all'infinito, rovinando l'immagine per un problema che non esiste.
    """
    return bool(imaging.decoders())


def _to_gray(image) -> np.ndarray:
    return np.ascontiguousarray(np.array(image.convert("L")))


def _degrade(gray: np.ndarray, target_px: int, blur: float, noise: float) -> np.ndarray:
    out = gray
    if target_px and target_px != gray.shape[0]:
        out = imaging.resize_gray(out, target_px, target_px)
    if blur > 0:
        out = np.clip(imaging.gaussian_blur(out.astype(np.float64), blur), 0, 255).astype(np.uint8)
    if noise > 0:
        rng = np.random.default_rng(12345)
        out = np.clip(out.astype(np.float32) + rng.normal(0, noise, out.shape), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(out)


# (etichetta, pixel per modulo, sigma blur, sigma rumore).
# La risoluzione si misura in pixel per modulo, non in pixel assoluti: un
# simbolo a 45 moduli ne richiede il doppio di uno a 21 per essere letto alla
# stessa distanza. Sotto i 3 px/modulo nemmeno un QR normale si decodifica.
CONDITIONS: list[tuple[str, float, float, float]] = [
    ("nativo", 0, 0.0, 0.0),
    ("12 px/mod", 12, 0.0, 0.0),
    ("8 px/mod", 8, 0.0, 0.0),
    ("6 px/mod", 6, 0.0, 0.0),
    ("5 px/mod", 5, 0.0, 0.0),
    ("4 px/mod", 4, 0.0, 0.0),
    ("8 px/mod sfocato", 8, 1.6, 0.0),
    ("6 px/mod sfocato", 6, 1.1, 0.0),
    ("8 px/mod rumoroso", 8, 0.7, 10.0),
    ("5 px/mod rumoroso", 5, 0.5, 7.0),
]


def check(image, payload: str, modules: int, conditions=CONDITIONS) -> Report:
    """Ridecodifica `image` (PIL) in ogni condizione e confronta con `payload`.

    `modules` e' il lato del simbolo in moduli, quiet zone inclusa: serve a
    convertire i pixel per modulo in una dimensione concreta.
    """
    gray = _to_gray(image)
    report = Report(payload=payload, total=len(conditions))
    for label, ppm, blur, noise in conditions:
        target = int(round(ppm * modules)) if ppm else 0
        if payload in imaging.decode_qr(_degrade(gray, target, blur, noise)):
            report.passed += 1
        else:
            report.failures.append(label)
    report.decoders.update(imaging.decoders())
    return report


def fidelity(dark_px: np.ndarray, target: np.ndarray, scale: int) -> float:
    """Quanto il risultato somiglia ancora alla foto, fra 0 e 1.

    L'occhio non legge i singoli pixel di un halftone: a distanza li media. Si
    confronta quindi la versione sfocata del risultato con la luminanza voluta,
    tramite correlazione di Pearson - insensibile a scostamenti uniformi di
    luminosita' o contrasto, che non cambiano la riconoscibilita' del soggetto.
    """
    got = imaging.gaussian_blur(np.where(dark_px, 0.0, 1.0), scale * 0.6)
    want = imaging.gaussian_blur(target.astype(np.float64), scale * 0.6)
    a, b = got.ravel() - got.mean(), want.ravel() - want.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / denom) if denom > 1e-9 else 0.0


def baseline(payload: str, version: int, error: str = "H", border: int = 4) -> Report:
    """Punteggio di un QR normale con gli stessi parametri: il tetto raggiungibile."""
    from io import BytesIO

    import segno
    from PIL import Image

    qr = segno.make(payload, version=version, error=error, micro=False, boost_error=False)
    buf = BytesIO()
    qr.save(buf, kind="png", scale=9, border=border)
    buf.seek(0)
    return check(Image.open(buf), payload, qr.symbol_size(scale=1, border=border)[0])
