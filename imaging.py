"""Operazioni sulle immagini, con o senza OpenCV.

OpenCV e' un wheel nativo da decine di megabyte: su Windows, Linux e macOS si
installa senza pensarci, su iOS (a-Shell, Pythonista) non esiste proprio. Tutto
quello che serve al generatore - sfocatura, ridimensionamento, equalizzazione,
contrasto locale - e' pero' esprimibile in numpy e Pillow, che ci sono ovunque.

Qui sta quell'implementazione. Se OpenCV e' installato viene usato lui, perche'
e' piu' veloce; altrimenti si passa al percorso puro. I risultati non sono
identici al bit (i bordi vengono trattati in modo leggermente diverso), ma sono
equivalenti nella sostanza: i test lo verificano confrontando i due percorsi.
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image

_CASCADES = ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml")

try:
    import cv2

    HAS_CV2 = True
except ImportError:  # pragma: no cover - dipende dall'installazione
    cv2 = None
    HAS_CV2 = False

try:
    from pyzbar import pyzbar as _pyzbar

    HAS_ZBAR = True
except Exception:  # pragma: no cover - richiede la libreria nativa libzbar
    _pyzbar = None
    HAS_ZBAR = False


def _gaussian_kernel(sigma: float) -> np.ndarray:
    radius = max(1, int(round(sigma * 3)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-(x * x) / (2.0 * sigma * sigma))
    return k / k.sum()


def gaussian_blur(arr: np.ndarray, sigma: float) -> np.ndarray:
    """Sfocatura gaussiana su un array 2D di float."""
    if sigma <= 0:
        return arr.astype(np.float64, copy=True)
    if HAS_CV2:
        return cv2.GaussianBlur(arr.astype(np.float64), (0, 0), sigmaX=sigma)

    # Convoluzione separabile: due passate 1D invece di una 2D.
    k = _gaussian_kernel(sigma)
    pad = len(k) // 2
    src = arr.astype(np.float64)

    # "reflect" di numpy riflette senza ripetere il pixel di bordo: e' lo stesso
    # BORDER_REFLECT_101 che OpenCV usa in modo predefinito. Allinearsi conta,
    # perche' altrimenti lo stesso simbolo otterrebbe punteggi di leggibilita'
    # diversi a seconda della piattaforma. Su immagini piu' piccole del kernel
    # la riflessione non e' definita e si ripiega sulla replica del bordo.
    mode = "reflect" if min(src.shape) > pad else "edge"

    tmp = np.pad(src, ((0, 0), (pad, pad)), mode=mode)
    horiz = np.zeros_like(src)
    for i, weight in enumerate(k):
        horiz += weight * tmp[:, i : i + src.shape[1]]

    tmp = np.pad(horiz, ((pad, pad), (0, 0)), mode=mode)
    out = np.zeros_like(src)
    for i, weight in enumerate(k):
        out += weight * tmp[i : i + src.shape[0], :]
    return out


def resize_gray(arr: np.ndarray, width: int, height: int) -> np.ndarray:
    """Ridimensiona un array uint8 in scala di grigi, con media sui rimpicciolimenti."""
    if (arr.shape[1], arr.shape[0]) == (width, height):
        return np.ascontiguousarray(arr)
    if HAS_CV2:
        shrinking = width < arr.shape[1]
        interp = cv2.INTER_AREA if shrinking else cv2.INTER_LINEAR
        return np.ascontiguousarray(cv2.resize(arr, (width, height), interpolation=interp))
    # BOX equivale a INTER_AREA sui rimpicciolimenti, che e' il caso che conta:
    # mediare i pixel invece di campionarli e' cio' che simula una fotocamera.
    resample = Image.BOX if width < arr.shape[1] else Image.BILINEAR
    out = Image.fromarray(arr, mode="L").resize((width, height), resample)
    return np.ascontiguousarray(np.asarray(out))


def equalize(arr: np.ndarray) -> np.ndarray:
    """Equalizzazione dell'istogramma su tutta l'immagine (uint8)."""
    if HAS_CV2:
        return cv2.equalizeHist(arr)
    hist = np.bincount(arr.ravel(), minlength=256).astype(np.float64)
    cdf = hist.cumsum()
    total = cdf[-1]
    if total <= 0:
        return arr.copy()
    lut = np.round(255.0 * cdf / total).astype(np.uint8)
    return lut[arr]


def clahe(arr: np.ndarray, clip_limit: float = 2.0, tiles: int = 8) -> np.ndarray:
    """Contrasto locale adattivo (CLAHE) su un'immagine uint8.

    L'immagine viene divisa in `tiles`x`tiles` riquadri; per ognuno si costruisce
    la curva di equalizzazione, limitando prima l'altezza dell'istogramma e
    ridistribuendo l'eccedenza - e' il "contrast limited" del nome, senza il
    quale il rumore delle zone piatte verrebbe amplificato. Le curve dei riquadri
    vicini vengono poi fuse per interpolazione, altrimenti si vedrebbero i bordi.
    """
    if clip_limit <= 0:
        return arr.copy()
    if HAS_CV2:
        return cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tiles, tiles)).apply(arr)

    h, w = arr.shape
    ty = min(tiles, max(1, h))
    tx = min(tiles, max(1, w))
    edges_y = np.linspace(0, h, ty + 1).astype(int)
    edges_x = np.linspace(0, w, tx + 1).astype(int)

    luts = np.zeros((ty, tx, 256), dtype=np.float64)
    for i in range(ty):
        for j in range(tx):
            tile = arr[edges_y[i] : edges_y[i + 1], edges_x[j] : edges_x[j + 1]]
            hist = np.bincount(tile.ravel(), minlength=256).astype(np.float64)
            count = tile.size
            if count == 0:
                luts[i, j] = np.arange(256)
                continue
            # Taglia i picchi e ridistribuisce l'eccedenza su tutti i livelli.
            limit = max(1.0, clip_limit * count / 256.0)
            excess = np.maximum(hist - limit, 0.0).sum()
            hist = np.minimum(hist, limit) + excess / 256.0
            cdf = hist.cumsum()
            luts[i, j] = 255.0 * (cdf - cdf[0]) / max(cdf[-1] - cdf[0], 1e-9)

    # Interpolazione bilineare fra le curve dei riquadri, sui loro centri.
    centers_y = (edges_y[:-1] + edges_y[1:] - 1) / 2.0
    centers_x = (edges_x[:-1] + edges_x[1:] - 1) / 2.0
    yy = np.arange(h, dtype=np.float64)
    xx = np.arange(w, dtype=np.float64)

    fy = np.interp(yy, centers_y, np.arange(ty, dtype=np.float64))
    fx = np.interp(xx, centers_x, np.arange(tx, dtype=np.float64))
    i0 = np.floor(fy).astype(int)
    j0 = np.floor(fx).astype(int)
    i1 = np.minimum(i0 + 1, ty - 1)
    j1 = np.minimum(j0 + 1, tx - 1)
    wy = (fy - i0)[:, None]
    wx = (fx - j0)[None, :]

    i0g, i1g = i0[:, None], i1[:, None]
    j0g, j1g = j0[None, :], j1[None, :]
    out = (
        (1 - wy) * (1 - wx) * luts[i0g, j0g, arr]
        + (1 - wy) * wx * luts[i0g, j1g, arr]
        + wy * (1 - wx) * luts[i1g, j0g, arr]
        + wy * wx * luts[i1g, j1g, arr]
    )
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


def face_detection_available() -> bool:
    """Vero se il rilevamento del volto e' utilizzabile.

    Serve OpenCV con i classificatori a cascata di Haar e i relativi file XML.
    OpenCV 5 ha tolto `CascadeClassifier` dal pacchetto (resta il solo
    rilevatore DNN, che richiede un modello da scaricare a parte), quindi la
    presenza di OpenCV non basta a garantirlo.
    """
    if not HAS_CV2 or not hasattr(cv2, "CascadeClassifier"):
        return False
    folder = getattr(getattr(cv2, "data", None), "haarcascades", None)
    return bool(folder) and os.path.isfile(os.path.join(folder, _CASCADES[0]))


def detect_face(arr: np.ndarray) -> tuple[int, int, int, int] | None:
    """Riquadro del volto piu' grande in un'immagine uint8, se rilevabile.

    Restituisce None quando il rilevamento non e' disponibile: l'inquadratura
    ricade allora sul centro dell'immagine.
    """
    if not face_detection_available():
        return None

    scale = 1.0
    gray = arr
    if max(gray.shape) > 900:
        scale = 900 / max(gray.shape)
        gray = resize_gray(gray, int(gray.shape[1] * scale), int(gray.shape[0] * scale))
    gray = equalize(gray)

    best: tuple[int, int, int, int] | None = None
    for name in _CASCADES:
        cascade = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, name))
        if cascade.empty():
            continue
        for x, y, fw, fh in cascade.detectMultiScale(gray, 1.1, 5, minSize=(40, 40)):
            if best is None or fw * fh > best[2] * best[3]:
                best = (int(x), int(y), int(fw), int(fh))
        if best is not None:
            break

    if best is None:
        return None
    return tuple(int(round(v / scale)) for v in best)  # type: ignore[return-value]


def decode_qr(gray: np.ndarray) -> set[str]:
    """Decodifica i QR presenti, con ogni decoder disponibile."""
    found: set[str] = set()
    if HAS_ZBAR:
        for sym in _pyzbar.decode(gray, symbols=[_pyzbar.ZBarSymbol.QRCODE]):
            found.add(sym.data.decode("utf-8", errors="replace"))
    if HAS_CV2:
        try:
            data, _points, _ = cv2.QRCodeDetector().detectAndDecode(gray)
            if data:
                found.add(data)
        except cv2.error:
            pass
    return found


def decoders() -> list[str]:
    """Nomi dei decoder QR utilizzabili; vuota se la verifica non e' possibile."""
    names = []
    if HAS_ZBAR:
        names.append("zbar")
    if HAS_CV2:
        names.append("opencv")
    return names


def backend() -> str:
    """Descrizione del percorso in uso, per i messaggi diagnostici."""
    return "opencv" if HAS_CV2 else "numpy/pillow"
