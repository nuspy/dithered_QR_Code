"""Test del generatore. Eseguire con: pytest -q"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import segno
from PIL import Image

import imaging
import verify
from dither import METHODS, dither
from dithered_qr import (
    MEAN_SLACK,
    Settings,
    build_symbol,
    choose_version,
    compose,
    function_map,
    generate,
    generate_verified,
    module_deficit,
    resolve,
)
from qr_layout import function_masks, verify_layout

PAYLOAD = "https://example.com/test"


@pytest.fixture(scope="module")
def photo(tmp_path_factory) -> Path:
    """Un finto ritratto: gradiente, un disco chiaro e dettagli fini."""
    side = 600
    y, x = np.mgrid[0:side, 0:side]
    img = 40 + 160 * (y / side)
    disc = (x - side * 0.5) ** 2 + (y - side * 0.42) ** 2 < (side * 0.28) ** 2
    img[disc] = 225
    img += 25 * np.sin(x / 7.0) * np.cos(y / 9.0)
    path = tmp_path_factory.mktemp("img") / "photo.png"
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), mode="L").save(path)
    return path


# --------------------------------------------------------------------------
# geometria del simbolo
# --------------------------------------------------------------------------

def test_layout_valido_per_tutte_le_versioni():
    """La mappa dei moduli funzionali deve combaciare con i simboli reali.

    E' il controllo che protegge dall'errore piu' insidioso: una tabella di
    alignment sbagliata farebbe scrivere l'immagine sopra un pattern di servizio
    rendendo il QR illeggibile senza alcun sintomo visibile.
    """
    for version in range(1, 41):
        qr = segno.make("A" * 4, version=version, error="h", micro=False, boost_error=False)
        matrix = np.array([list(r) for r in qr.matrix], dtype=bool)
        verify_layout(matrix, version)


def test_maschere_funzionali_non_si_sovrappongono():
    hard, soft = function_masks(14, 17 + 4 * 14)
    assert not (hard & soft).any()


def test_versione_minima_rispettata():
    cfg = Settings(min_version=14)
    assert choose_version("ciao", cfg) == 14
    # Un testo che non ci sta in versione 14 fa salire di versione.
    assert choose_version("x" * 400, cfg) > 14
    # Una versione esplicita ha la precedenza.
    assert choose_version("ciao", Settings(version=9, min_version=14)) == 9


# --------------------------------------------------------------------------
# dithering
# --------------------------------------------------------------------------

@pytest.mark.parametrize("method", METHODS)
def test_dithering_rispetta_i_vincoli(method):
    rng = np.random.default_rng(7)
    lum = rng.random((48, 48))
    forced = np.full((48, 48), -1, dtype=np.int8)
    forced[::5, ::5] = 0        # imposti scuri
    forced[2::7, 3::7] = 1      # imposti chiari

    out = dither(lum, forced, method=method)
    assert out[forced == 0].all()
    assert not out[forced == 1].any()


def test_diffusione_conserva_la_media():
    """La proprieta' su cui poggia tutto il generatore."""
    lum = np.full((64, 64), 0.30)
    out = dither(lum, method="floyd-steinberg")
    assert abs(out.mean() - 0.70) < 0.02   # 30% di luce = 70% di pixel scuri


def test_metodo_sconosciuto():
    with pytest.raises(ValueError):
        dither(np.zeros((4, 4)), method="inesistente")


# --------------------------------------------------------------------------
# composizione
# --------------------------------------------------------------------------

def test_compose_centra_la_media_di_ogni_modulo(photo):
    from dithered_qr import load_luminance

    cfg = resolve(Settings(min_version=7))
    matrix, version, _ = build_symbol(PAYLOAD, cfg)
    size = matrix.shape[0]
    lum = load_luminance(photo, size * cfg.scale, cfg)

    out, forced, _, _ = compose(matrix, version, lum, cfg)
    means = out.reshape(size, cfg.scale, size, cfg.scale).mean(axis=(1, 3))
    goal = np.where(matrix, 0.5 - cfg.margin - MEAN_SLACK, 0.5 + cfg.margin + MEAN_SLACK)
    data = ~function_map(matrix, version, cfg)

    # Nessun modulo dati deve restare dalla parte sbagliata dell'obiettivo.
    wrong = np.where(matrix, means - goal, goal - means)[data]
    assert wrong.max() < 1e-6


def test_nessun_modulo_in_minoranza_dopo_il_dithering(photo):
    from dithered_qr import load_luminance

    cfg = resolve(Settings(min_version=7))
    matrix, version, _ = build_symbol(PAYLOAD, cfg)
    lum = load_luminance(photo, matrix.shape[0] * cfg.scale, cfg)

    out, forced, _, sacrificed = compose(matrix, version, lum, cfg)
    dark = dither(out, forced, method=cfg.method)
    skip = function_map(matrix, version, cfg) | sacrificed
    assert not module_deficit(dark, matrix, skip, cfg).any()


def test_moduli_funzionali_riprodotti_esattamente(photo):
    """Finder e timing devono uscire identici al simbolo di partenza."""
    cfg = resolve(Settings(min_version=7))
    result = generate(PAYLOAD, photo, cfg)
    matrix, version, _ = build_symbol(PAYLOAD, replace_mask(cfg, result.mask))

    arr = np.array(result.image.convert("L"))
    pad = cfg.border * cfg.scale
    inner = arr[pad:-pad, pad:-pad] < 128        # True = scuro
    size = matrix.shape[0]
    got = inner.reshape(size, cfg.scale, size, cfg.scale)

    full = function_map(matrix, version, cfg)
    for r, c in zip(*np.nonzero(full)):
        block = got[r, :, c, :]
        if matrix[r, c]:
            assert block.all(), f"modulo scuro ({r},{c}) non pieno"
        else:
            assert not block.any(), f"modulo chiaro ({r},{c}) sporcato"


def replace_mask(cfg: Settings, mask: int) -> Settings:
    from dataclasses import replace

    return replace(cfg, mask=mask)


# --------------------------------------------------------------------------
# risultato finale
# --------------------------------------------------------------------------

def test_il_qr_generato_si_decodifica(photo):
    result = generate(PAYLOAD, photo, Settings(min_version=7))
    assert PAYLOAD in verify.decode(np.array(result.image.convert("L")))


def test_leggibile_anche_rimpicciolito(photo):
    result = generate_verified(PAYLOAD, photo, Settings(min_version=7), quiet=True)
    assert result.report is not None
    assert result.report.score >= 0.9


def test_immagine_presente_non_solo_qr(photo):
    """La foto deve restare riconoscibile, non ridursi a rumore."""
    result = generate(PAYLOAD, photo, Settings(min_version=7))
    assert result.fidelity > 0.3


def test_quiet_zone_bianca(photo):
    cfg = Settings(min_version=7, border=4)
    result = generate(PAYLOAD, photo, cfg)
    arr = np.array(result.image.convert("L"))
    pad = cfg.border * cfg.scale
    assert (arr[:pad, :] == 255).all()
    assert (arr[-pad:, :] == 255).all()
    assert (arr[:, :pad] == 255).all()


def test_colori_personalizzati(photo):
    result = generate(PAYLOAD, photo, Settings(min_version=7, dark="#102030", light="#fbf0e0"))
    colors = {tuple(c) for c in np.array(result.image).reshape(-1, 3)}
    assert colors == {(16, 32, 48), (251, 240, 224)}


def test_ingrandimento_solo_a_fattore_intero(photo):
    """Moduli di larghezza disuguale fanno perdere la griglia allo scanner."""
    cfg = Settings(min_version=7, scale=9, border=4)
    native = generate(PAYLOAD, photo, cfg).image.width

    grown = generate(PAYLOAD, photo, Settings(min_version=7, out_size=native + 1)).image
    assert grown.width == native * 2 >= native + 1

    # Un lato richiesto piu' piccolo del nativo non rimpicciolisce: ridurre un
    # halftone lo trasformerebbe in grigio.
    same = generate(PAYLOAD, photo, Settings(min_version=7, out_size=native // 2)).image
    assert same.width == native


@pytest.mark.parametrize("bad", [dict(scale=8), dict(scale=1), dict(core=4), dict(blend=2.0)])
def test_parametri_non_validi(bad):
    with pytest.raises(ValueError):
        resolve(Settings(**bad))


def test_core_predefinito_segue_scale():
    assert resolve(Settings(scale=9)).core == 3
    assert resolve(Settings(scale=15)).core == 5
    assert resolve(Settings(scale=3)).core == 1


# --------------------------------------------------------------------------
# verifica
# --------------------------------------------------------------------------

def test_batteria_equa_per_un_qr_normale():
    """Se un QR ordinario non passasse le prove, il punteggio non direbbe nulla."""
    for version in (3, 8, 14):
        assert verify.baseline(PAYLOAD, version=version).score == 1.0


# --------------------------------------------------------------------------
# percorso senza OpenCV (iOS e installazioni minime)
# --------------------------------------------------------------------------

@pytest.fixture
def senza_cv2(monkeypatch):
    """Forza il percorso puro numpy/Pillow anche se OpenCV e' installato."""
    monkeypatch.setattr(imaging, "HAS_CV2", False)
    return imaging


@pytest.mark.skipif(not imaging.HAS_CV2, reason="serve OpenCV per il confronto")
def test_sfocatura_equivale_a_quella_di_opencv(monkeypatch):
    rng = np.random.default_rng(11)
    arr = rng.random((80, 80))
    con = imaging.gaussian_blur(arr, 2.0)
    monkeypatch.setattr(imaging, "HAS_CV2", False)
    senza = imaging.gaussian_blur(arr, 2.0)
    assert np.abs(con - senza).max() < 0.01


@pytest.mark.skipif(not imaging.HAS_CV2, reason="serve OpenCV per il confronto")
def test_clahe_equivale_a_quello_di_opencv(monkeypatch):
    rng = np.random.default_rng(5)
    base = np.clip(rng.normal(120, 45, (200, 200)), 0, 255).astype(np.uint8)
    con = imaging.clahe(base, 2.0, tiles=8).astype(np.float64)
    monkeypatch.setattr(imaging, "HAS_CV2", False)
    senza = imaging.clahe(base, 2.0, tiles=8).astype(np.float64)

    a, b = con.ravel() - con.mean(), senza.ravel() - senza.mean()
    correlazione = (a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum())
    assert correlazione > 0.97


@pytest.mark.skipif(not imaging.HAS_CV2, reason="serve OpenCV per il confronto")
def test_equalizzazione_equivale_a_quella_di_opencv(monkeypatch):
    rng = np.random.default_rng(2)
    base = np.clip(rng.normal(110, 30, (64, 64)), 0, 255).astype(np.uint8)
    con = imaging.equalize(base).astype(int)
    monkeypatch.setattr(imaging, "HAS_CV2", False)
    assert np.abs(con - imaging.equalize(base).astype(int)).max() <= 1


def test_genera_e_si_decodifica_senza_opencv(senza_cv2, photo):
    """Il generatore deve funzionare dove OpenCV non esiste, come su iOS."""
    result = generate(PAYLOAD, photo, Settings(min_version=7))
    assert result.fidelity > 0.3
    if imaging.HAS_ZBAR:
        assert PAYLOAD in imaging.decode_qr(np.array(result.image.convert("L")))


def test_inquadratura_ricade_sul_centro_senza_rilevamento(senza_cv2, photo):
    from PIL import Image as PILImage

    from framing import square_crop

    img = PILImage.open(photo)
    ritaglio = square_crop(img, focus="face")
    assert ritaglio.size == (min(img.size), min(img.size))


def test_verifica_saltata_senza_decoder(monkeypatch, photo):
    """Senza decoder il punteggio non deve essere confuso con uno zero."""
    monkeypatch.setattr(imaging, "HAS_CV2", False)
    monkeypatch.setattr(imaging, "HAS_ZBAR", False)
    assert not verify.available()

    result = generate_verified(PAYLOAD, photo, Settings(min_version=7), quiet=True)
    assert result.report is None
    assert result.settings.margin == Settings().margin      # nessun irrigidimento


# --------------------------------------------------------------------------
# interfaccia web
# --------------------------------------------------------------------------

def test_pagina_web_e_mobile():
    """La pagina deve reggere uno schermo stretto, non solo un monitor."""
    import webgui

    page = webgui.build_page()
    # Senza questo meta la pagina viene rimpicciolita e i comandi diventano
    # impossibili da toccare; viewport-fit serve al notch.
    assert 'name="viewport"' in page and "viewport-fit=cover" in page
    assert "env(safe-area-inset-bottom)" in page      # barra azioni sopra il gesto
    assert "prefers-color-scheme: dark" in page       # tema scuro
    assert "prefers-reduced-motion" in page           # animazioni disattivabili
    assert "min-height: 48px" in page                 # bersagli tattili
    assert "font-size: 16px" in page                  # iOS ingrandisce sotto i 16px
    assert ":focus-visible" in page                   # navigazione da tastiera
    # Tutto inline: la pagina deve funzionare senza rete.
    assert "http://" not in page.split("<style>")[1].split("</style>")[0]


def test_pagina_web_elenca_i_profili_tradotti():
    import webgui

    page = webgui.build_page()
    for label in ("Photo first", "Balanced", "Robust"):
        assert label in page
    assert "equilibrato" in page          # il valore interno resta quello


def test_api_web_genera_e_confina_i_percorsi(tmp_path, photo):
    """Il salvataggio non deve poter scrivere fuori dalla cartella scelta."""
    import base64

    import webgui

    handler = webgui.Handler.__new__(webgui.Handler)
    handler.save_dir = tmp_path

    payload = {
        "image": base64.b64encode(photo.read_bytes()).decode(),
        "text": PAYLOAD,
        "verify": False,
        "settings": {"min_version": 7},
    }
    out = handler._generate(payload)
    assert out["png"] and "Version" in out["details"]

    # Un nome con percorso viene ridotto al solo nome file.
    saved = handler._save({"png": out["png"], "name": "../../fuori.png"})
    assert Path(saved["path"]).parent == tmp_path
    assert not (tmp_path.parent / "fuori.png").exists()

    # L'estensione mancante viene aggiunta.
    assert handler._save({"png": out["png"], "name": "senza"})["name"] == "senza.png"

    for cattivo in ({"text": PAYLOAD}, {"image": payload["image"], "text": ""}):
        with pytest.raises(ValueError):
            handler._generate(cattivo)


def test_api_web_rifiuta_immagini_non_valide():
    import base64

    import webgui

    handler = webgui.Handler.__new__(webgui.Handler)
    with pytest.raises(ValueError):
        handler._generate({"image": base64.b64encode(b"non e' una immagine").decode(),
                           "text": PAYLOAD})


def test_fedelta_riconosce_una_copia_e_un_rumore():
    rng = np.random.default_rng(3)
    target = np.repeat(np.repeat(rng.random((20, 20)), 9, axis=0), 9, axis=1)
    same = dither(target, method="floyd-steinberg")
    assert verify.fidelity(same, target, 9) > 0.8
    noise = rng.random(target.shape) < 0.5
    assert abs(verify.fidelity(noise, target, 9)) < 0.2
