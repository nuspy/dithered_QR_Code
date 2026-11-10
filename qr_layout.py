"""Geometria di un simbolo QR: quali moduli sono funzionali e quali portano dati.

I moduli funzionali (finder, separatori, timing, alignment, format/version info)
devono restare intatti perche' il decoder li usa per ricostruire la griglia.
I moduli dati possono invece essere "ammorbiditi": basta che il loro centro
abbia il colore giusto, perche' e' li' che lo scanner campiona.
"""

from __future__ import annotations

import numpy as np

# ISO/IEC 18004, Annex E - coordinate dei centri degli alignment pattern.
ALIGNMENT_CENTERS: dict[int, list[int]] = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
    11: [6, 30, 54],
    12: [6, 32, 58],
    13: [6, 34, 62],
    14: [6, 26, 46, 66],
    15: [6, 26, 48, 70],
    16: [6, 26, 50, 74],
    17: [6, 30, 54, 78],
    18: [6, 30, 56, 82],
    19: [6, 30, 58, 86],
    20: [6, 34, 62, 90],
    21: [6, 28, 50, 72, 94],
    22: [6, 26, 50, 74, 98],
    23: [6, 30, 54, 78, 102],
    24: [6, 28, 54, 80, 106],
    25: [6, 32, 58, 84, 110],
    26: [6, 30, 58, 86, 114],
    27: [6, 34, 62, 90, 118],
    28: [6, 26, 50, 74, 98, 122],
    29: [6, 30, 54, 78, 102, 126],
    30: [6, 26, 52, 78, 104, 130],
    31: [6, 30, 56, 82, 108, 134],
    32: [6, 34, 60, 86, 112, 138],
    33: [6, 30, 58, 86, 114, 142],
    34: [6, 34, 62, 90, 118, 146],
    35: [6, 30, 54, 78, 102, 126, 150],
    36: [6, 24, 50, 76, 102, 128, 154],
    37: [6, 28, 54, 80, 106, 132, 158],
    38: [6, 32, 58, 84, 110, 136, 162],
    39: [6, 26, 54, 82, 110, 138, 166],
    40: [6, 30, 58, 86, 114, 142, 170],
}

FINDER = np.array(
    [
        [1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1],
    ],
    dtype=bool,
)

ALIGNMENT = np.array(
    [
        [1, 1, 1, 1, 1],
        [1, 0, 0, 0, 1],
        [1, 0, 1, 0, 1],
        [1, 0, 0, 0, 1],
        [1, 1, 1, 1, 1],
    ],
    dtype=bool,
)


def alignment_centers(version: int) -> list[tuple[int, int]]:
    """Centri degli alignment pattern, esclusi i tre occupati dai finder."""
    coords = ALIGNMENT_CENTERS[version]
    if not coords:
        return []
    last = coords[-1]
    skip = {(6, 6), (6, last), (last, 6)}
    return [(r, c) for r in coords for c in coords if (r, c) not in skip]


def function_masks(version: int, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Restituisce (rigide, morbide).

    - `rigide`: moduli che vanno riprodotti pixel per pixel (finder, separatori,
      format info). Senza questi il decoder non aggancia nemmeno il simbolo.
    - `morbide`: timing, alignment e version info. Sono funzionali, ma un decoder
      tollerante li ritrova anche se solo il nucleo del modulo e' corretto; sono
      separati per poterli rendere opzionalmente meno invadenti nell'immagine.
    """
    hard = np.zeros((size, size), dtype=bool)
    soft = np.zeros((size, size), dtype=bool)

    # Finder + separatori: blocchi 8x8 nei tre angoli.
    hard[0:8, 0:8] = True
    hard[0:8, size - 8 : size] = True
    hard[size - 8 : size, 0:8] = True

    # Format info (include il modulo scuro fisso in (size-8, 8)).
    hard[8, 0:9] = True
    hard[0:9, 8] = True
    hard[8, size - 8 : size] = True
    hard[size - 8 : size, 8] = True

    # Timing pattern.
    soft[6, :] = True
    soft[:, 6] = True

    # Alignment pattern.
    for r, c in alignment_centers(version):
        soft[r - 2 : r + 3, c - 2 : c + 3] = True

    # Version info (solo dalla versione 7 in poi).
    if version >= 7:
        soft[0:6, size - 11 : size - 8] = True
        soft[size - 11 : size - 8, 0:6] = True

    soft &= ~hard
    return hard, soft


def verify_layout(matrix: np.ndarray, version: int) -> None:
    """Controlla che la mappa dei moduli funzionali combaci con il simbolo reale.

    Se la tabella degli alignment fosse sbagliata per una versione, il generatore
    scriverebbe l'immagine sopra un pattern di servizio e il QR diventerebbe
    illeggibile in modo silenzioso. Meglio fallire subito.
    """
    size = matrix.shape[0]
    expected_size = 17 + 4 * version
    if size != expected_size:
        raise ValueError(f"versione {version}: attesa matrice {expected_size}, trovata {size}")

    for r, c in ((0, 0), (0, size - 7), (size - 7, 0)):
        if not np.array_equal(matrix[r : r + 7, c : c + 7], FINDER):
            raise ValueError(f"finder pattern non riconosciuto in ({r}, {c})")

    for r, c in alignment_centers(version):
        block = matrix[r - 2 : r + 3, c - 2 : c + 3]
        if not np.array_equal(block, ALIGNMENT):
            raise ValueError(f"alignment pattern atteso in ({r}, {c}) ma non trovato")

    # Timing pattern: alternanza scuro/chiaro a partire da scuro.
    timing_row = matrix[6, 8 : size - 8]
    if not np.array_equal(timing_row, np.arange(8, size - 8) % 2 == 0):
        raise ValueError("timing pattern orizzontale inatteso")
