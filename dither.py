"""Dithering a diffusione d'errore con pixel vincolati.

La variante vincolata e' il cuore del generatore: i pixel che formano i nuclei
dei moduli QR hanno un valore imposto, e l'errore che quel valore introduce
rispetto alla luminanza desiderata viene diffuso ai vicini come per qualunque
altro pixel. Cosi' l'immagine si "riadatta" attorno ai vincoli invece di
subirli, e il ritratto resta leggibile anche con un decimo dei pixel bloccati.
"""

from __future__ import annotations

import numpy as np

# (dx, dy, peso) con i pesi gia' normalizzati sul divisore del kernel.
KERNELS: dict[str, list[tuple[int, int, float]]] = {
    "floyd-steinberg": [
        (1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16),
    ],
    "atkinson": [
        (1, 0, 1 / 8), (2, 0, 1 / 8), (-1, 1, 1 / 8), (0, 1, 1 / 8),
        (1, 1, 1 / 8), (0, 2, 1 / 8),
    ],
    "jarvis": [
        (1, 0, 7 / 48), (2, 0, 5 / 48),
        (-2, 1, 3 / 48), (-1, 1, 5 / 48), (0, 1, 7 / 48), (1, 1, 5 / 48), (2, 1, 3 / 48),
        (-2, 2, 1 / 48), (-1, 2, 3 / 48), (0, 2, 5 / 48), (1, 2, 3 / 48), (2, 2, 1 / 48),
    ],
    "sierra": [
        (1, 0, 5 / 32), (2, 0, 3 / 32),
        (-2, 1, 2 / 32), (-1, 1, 4 / 32), (0, 1, 5 / 32), (1, 1, 4 / 32), (2, 1, 2 / 32),
        (-1, 2, 2 / 32), (0, 2, 3 / 32), (1, 2, 2 / 32),
    ],
    "stucki": [
        (1, 0, 8 / 42), (2, 0, 4 / 42),
        (-2, 1, 2 / 42), (-1, 1, 4 / 42), (0, 1, 8 / 42), (1, 1, 4 / 42), (2, 1, 2 / 42),
        (-2, 2, 1 / 42), (-1, 2, 2 / 42), (0, 2, 4 / 42), (1, 2, 2 / 42), (2, 2, 1 / 42),
    ],
}

BAYER_8 = np.array(
    [
        [0, 32, 8, 40, 2, 34, 10, 42],
        [48, 16, 56, 24, 50, 18, 58, 26],
        [12, 44, 4, 36, 14, 46, 6, 38],
        [60, 28, 52, 20, 62, 30, 54, 22],
        [3, 35, 11, 43, 1, 33, 9, 41],
        [51, 19, 59, 27, 49, 17, 57, 25],
        [15, 47, 7, 39, 13, 45, 5, 37],
        [63, 31, 55, 23, 61, 29, 53, 21],
    ],
    dtype=np.float64,
)

METHODS = tuple(KERNELS) + ("bayer", "threshold")


def dither(
    lum: np.ndarray,
    forced: np.ndarray | None = None,
    method: str = "floyd-steinberg",
    serpentine: bool = True,
) -> np.ndarray:
    """Binarizza `lum` (float in [0, 1], 0 = nero) rispettando i pixel vincolati.

    `forced` e' un array di interi della stessa forma: -1 = pixel libero,
    0 = forzato scuro, 1 = forzato chiaro. Restituisce un array bool,
    True = pixel scuro.
    """
    if method not in METHODS:
        raise ValueError(f"metodo di dithering sconosciuto: {method}")
    if forced is None:
        forced = np.full(lum.shape, -1, dtype=np.int8)

    if method in ("bayer", "threshold"):
        if method == "bayer":
            h, w = lum.shape
            reps = (h // 8 + 1, w // 8 + 1)
            thresh = np.tile((BAYER_8 + 0.5) / 64.0, reps)[:h, :w]
        else:
            thresh = np.full(lum.shape, 0.5)
        out = lum < thresh
        out[forced == 0] = True
        out[forced == 1] = False
        return out

    return _diffuse(lum, forced, KERNELS[method], serpentine)


def _diffuse(
    lum: np.ndarray,
    forced: np.ndarray,
    kernel: list[tuple[int, int, float]],
    serpentine: bool,
) -> np.ndarray:
    """Diffusione d'errore riga per riga, con i pixel vincolati trattati come
    quantizzazioni gia' decise."""
    height, width = lum.shape
    buf = lum.astype(np.float64).copy()
    out = np.zeros((height, width), dtype=bool)
    forced_i = forced.astype(np.int8)

    for y in range(height):
        reverse = serpentine and (y % 2 == 1)
        xs = range(width - 1, -1, -1) if reverse else range(width)
        for x in xs:
            old = buf[y, x]
            constraint = forced_i[y, x]
            if constraint == 0:
                new = 0.0
            elif constraint == 1:
                new = 1.0
            else:
                new = 1.0 if old >= 0.5 else 0.0
            out[y, x] = new < 0.5
            error = old - new
            if error == 0.0:
                continue
            for dx, dy, weight in kernel:
                nx = x - dx if reverse else x + dx
                ny = y + dy
                if 0 <= nx < width and ny < height:
                    buf[ny, nx] += error * weight
    return out
