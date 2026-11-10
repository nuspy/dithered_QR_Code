"""Ritaglio quadrato dell'immagine sorgente.

Un halftone QR ha pochissima risoluzione da spendere: un volto che occupa un
quarto del frame diventa illeggibile. Qui si cerca il soggetto (volto, se c'e')
e si ritaglia un quadrato che lo riempia.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

import imaging

# Gli avvisi viaggiano come codici, non come frasi: il nucleo non sa in che
# lingua parla chi lo sta usando. La riga di comando e' in italiano, la finestra
# grafica in inglese, e ciascuna traduce questi codici per conto proprio.
FACE_DETECTION_UNAVAILABLE = "face-detection-unavailable"
NO_FACE_FOUND = "no-face-found"


def detect_face(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Riquadro (x, y, w, h) del volto piu' grande, oppure None.

    Restituisce None anche quando il rilevamento non e' disponibile del tutto
    (senza OpenCV): in quel caso l'inquadratura ricade sul centro.
    """
    return imaging.detect_face(np.array(img.convert("L")))


def square_crop(
    img: Image.Image,
    focus: str = "face",
    center: tuple[float, float] = (0.5, 0.42),
    zoom: float = 1.0,
    warn=None,
) -> Image.Image:
    """Ritaglia un quadrato: sul volto se richiesto e trovato, altrimenti su `center`.

    `warn` riceve un messaggio quando l'inquadratura richiesta non e' ottenibile,
    perche' un ripiego silenzioso sul centro sposterebbe il soggetto senza dirlo.
    """
    w, h = img.size
    side = min(w, h)
    cx, cy = center[0] * w, center[1] * h

    if focus == "face":
        rilevabile = imaging.face_detection_available()
        if warn and not rilevabile:
            warn(FACE_DETECTION_UNAVAILABLE)
        face = detect_face(img)
        if warn and face is None and rilevabile:
            warn(NO_FACE_FOUND)
        if face is not None:
            fx, fy, fw, fh = face
            cx, cy = fx + fw / 2.0, fy + fh / 2.0
            # In un halftone il volto deve dominare il frame: con poche decine di
            # moduli, un volto che non occupa almeno meta' larghezza sparisce.
            side = min(side, max(int(fw * 1.7), int(side * 0.3)))
            cy += fh * 0.10  # scende appena, per includere il mento

    side = max(16, int(side / max(zoom, 0.05)))
    side = min(side, min(w, h))

    left = int(round(min(max(cx - side / 2, 0), w - side)))
    top = int(round(min(max(cy - side / 2, 0), h - side)))
    return img.crop((left, top, left + side, top + side))
