"""Interfaccia grafica minimale per dithered_qr (Windows, macOS, Linux).

Tkinter e' nella libreria standard e usa i dialoghi nativi del sistema, che e'
cio' che conta per aprire e salvare: l'utente ritrova le sue cartelle e le sue
abitudini invece di un selettore inventato.

La generazione gira in un thread separato. Non e' un vezzo: con la verifica
attiva un codice puo' richiedere qualche secondo, e una finestra che si blocca
sembra rotta.

    python gui.py
"""

from __future__ import annotations

import queue
import sys
import threading
import traceback
from dataclasses import replace
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import colorchooser, filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - dipende dall'installazione
    print(
        "Tkinter is not available.\n"
        "  Debian/Ubuntu: sudo apt-get install python3-tk\n"
        "  Fedora:        sudo dnf install python3-tkinter\n"
        "  Arch:          sudo pacman -S tk\n"
        "  macOS/Windows: reinstall Python from python.org\n"
        "On iPhone/iPad use the web interface instead: python3 webgui.py",
        file=sys.stderr,
    )
    raise SystemExit(1)

from PIL import Image, ImageTk

import framing
import imaging
from dither import METHODS
from dithered_qr import ERROR_LEVELS, PROFILES, Settings, generate, generate_verified

# Il nucleo segnala per codice; qui si traduce, perche' questa finestra parla
# inglese mentre la riga di comando parla italiano.
WARNINGS = {
    framing.FACE_DETECTION_UNAVAILABLE:
        "face detection unavailable (needs OpenCV 4.x) — centred crop; adjust with Framing and Zoom",
    framing.NO_FACE_FOUND:
        "no face detected — centred crop; adjust with Framing and Zoom",
}

# I profili hanno nomi italiani nel nucleo; qui si mostrano tradotti.
PROFILE_LABELS = {
    "foto": "Photo first",
    "equilibrato": "Balanced",
    "robusto": "Robust",
}
PROFILE_NAMES = {label: name for name, label in PROFILE_LABELS.items()}
PROFILE_HINTS = {
    "foto": "Best-looking image; scan close up and in focus.",
    "equilibrato": "Recognisable photo, readable in every test condition.",
    "robusto": "Easiest to scan: fewer, larger modules. For print and distance.",
}

PREVIEW_MAX = 460
IMAGE_TYPES = [
    ("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff"),
    ("All files", "*.*"),
]
SAVE_TYPES = [
    ("PNG image", "*.png"),
    ("WebP image", "*.webp"),
    ("JPEG image", "*.jpg"),
    ("BMP image", "*.bmp"),
    ("All files", "*.*"),
]


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Dithered QR")
        self.minsize(900, 620)

        self.result = None          # ultimo Result generato
        self.preview_image = None   # riferimento vivo, o Tk scarta l'immagine
        self.jobs: queue.Queue = queue.Queue()
        self.busy = False

        self._build_variables()
        self._build_layout()
        self._sync_profile()
        self.after(80, self._drain_jobs)

    # ----------------------------------------------------------------- stato

    def _build_variables(self) -> None:
        d = Settings()
        self.var_image = tk.StringVar()
        self.var_text = tk.StringVar(value="https://example.com")
        self.var_profile = tk.StringVar(value=PROFILE_LABELS["equilibrato"])
        self.var_margin = tk.DoubleVar(value=PROFILES["equilibrato"]["margin"])
        self.var_min_version = tk.IntVar(value=PROFILES["equilibrato"]["min_version"])
        self.var_scale = tk.IntVar(value=d.scale)
        self.var_method = tk.StringVar(value=d.method)
        self.var_error = tk.StringVar(value=d.error)
        self.var_contrast = tk.DoubleVar(value=d.contrast)
        self.var_clahe = tk.DoubleVar(value=d.clahe)
        self.var_sharpen = tk.DoubleVar(value=d.sharpen)
        self.var_zoom = tk.DoubleVar(value=d.zoom)
        self.var_focus = tk.StringVar(value=d.focus)
        self.var_quiet = tk.StringVar(value=d.quiet)
        self.var_dark = tk.StringVar(value=d.dark)
        self.var_light = tk.StringVar(value=d.light)
        self.var_verify = tk.BooleanVar(value=True)
        self.var_status = tk.StringVar(value="Choose an image and enter the text, then press Generate.")

    def _settings(self) -> Settings:
        return replace(
            Settings(),
            scale=self.var_scale.get(),
            margin=round(self.var_margin.get(), 3),
            min_version=self.var_min_version.get(),
            method=self.var_method.get(),
            error=self.var_error.get(),
            contrast=round(self.var_contrast.get(), 2),
            clahe=round(self.var_clahe.get(), 2),
            sharpen=round(self.var_sharpen.get(), 2),
            zoom=round(self.var_zoom.get(), 2),
            focus=self.var_focus.get(),
            quiet=self.var_quiet.get(),
            dark=self.var_dark.get(),
            light=self.var_light.get(),
        )

    # ---------------------------------------------------------------- layout

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=0, minsize=380)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, padding=(14, 12))
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(self, padding=(6, 12, 14, 12))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self._build_source(left)
        self._build_parameters(left)
        self._build_actions(left)
        self._build_preview(right)
        self._build_statusbar()

    def _build_source(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="Source", padding=10)
        box.grid(row=0, column=0, sticky="ew")
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Image").grid(row=0, column=0, sticky="w", pady=(0, 6))
        entry = ttk.Entry(box, textvariable=self.var_image)
        entry.grid(row=0, column=1, sticky="ew", padx=(8, 6), pady=(0, 6))
        ttk.Button(box, text="Browse…", command=self.choose_image, width=10) \
            .grid(row=0, column=2, sticky="e", pady=(0, 6))

        ttk.Label(box, text="Text / URL").grid(row=1, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.var_text).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0))

    def _build_parameters(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="Parameters", padding=10)
        box.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        box.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(box, text="Profile").grid(row=row, column=0, sticky="w", pady=3)
        combo = ttk.Combobox(box, textvariable=self.var_profile, state="readonly",
                             values=[PROFILE_LABELS[n] for n in PROFILES], width=14)
        combo.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=3)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_profile())
        row += 1

        self.lbl_hint = ttk.Label(box, text="", foreground="#606060", wraplength=330)
        self.lbl_hint.grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 4))
        row += 1

        # Il margine e' la manopola principale: piu' alto, piu' il codice si
        # legge; piu' basso, piu' la fotografia resta intatta.
        self.lbl_margin = ttk.Label(box, text="")
        row = self._add_slider(box, row, "Margin", self.var_margin, 0.0, 0.40, self.lbl_margin,
                               fmt="{:.2f}")
        row = self._add_spin(box, row, "Min version", self.var_min_version, 1, 40, 1)
        row = self._add_spin(box, row, "Pixels per module", self.var_scale, 3, 21, 2)
        row = self._add_combo(box, row, "Dithering", self.var_method, list(METHODS))
        row = self._add_combo(box, row, "Error correction", self.var_error, list(ERROR_LEVELS))
        row = self._add_combo(box, row, "Framing", self.var_focus, ["face", "center"])
        row = self._add_combo(box, row, "Quiet zone", self.var_quiet, ["white", "image"])

        self.lbl_zoom = ttk.Label(box, text="")
        row = self._add_slider(box, row, "Zoom", self.var_zoom, 0.5, 3.0, self.lbl_zoom)
        self.lbl_contrast = ttk.Label(box, text="")
        row = self._add_slider(box, row, "Contrast", self.var_contrast, 0.5, 2.5, self.lbl_contrast)
        self.lbl_clahe = ttk.Label(box, text="")
        row = self._add_slider(box, row, "Local contrast", self.var_clahe, 0.0, 6.0, self.lbl_clahe)
        self.lbl_sharpen = ttk.Label(box, text="")
        row = self._add_slider(box, row, "Sharpen", self.var_sharpen, 0.0, 2.0, self.lbl_sharpen)

        ttk.Label(box, text="Colours").grid(row=row, column=0, sticky="w", pady=3)
        colours = ttk.Frame(box)
        colours.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=3)
        # Il colore sta in un riquadro accanto al pulsante, non nel pulsante:
        # su macOS i pulsanti nativi ignorano il colore di sfondo e la scelta
        # dell'utente resterebbe invisibile.
        self.sw_dark = self._colour_field(colours, "Dark", self.var_dark)
        self.sw_light = self._colour_field(colours, "Light", self.var_light)
        row += 1

        self.chk_verify = ttk.Checkbutton(
            box, text="Verify readability (slower)", variable=self.var_verify)
        self.chk_verify.grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 0))
        if not imaging.decoders():
            self.var_verify.set(False)
            self.chk_verify.state(["disabled"])
            ttk.Label(box, text="No QR decoder installed: readability cannot be checked.",
                      foreground="#a05a00", wraplength=330).grid(
                row=row + 1, column=0, columnspan=3, sticky="w", pady=(2, 0))

    def _add_slider(self, box, row, label, var, lo, hi, value_label, fmt="{:.2f}"):
        ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", pady=3)
        scale = ttk.Scale(box, from_=lo, to=hi, variable=var, orient="horizontal")
        scale.grid(row=row, column=1, sticky="ew", padx=(8, 6), pady=3)
        value_label.grid(row=row, column=2, sticky="e", pady=3)
        value_label.configure(text=fmt.format(var.get()), width=5)
        var.trace_add("write", lambda *_a: value_label.configure(text=fmt.format(var.get())))
        return row + 1

    def _add_spin(self, box, row, label, var, lo, hi, step):
        ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Spinbox(box, from_=lo, to=hi, increment=step, textvariable=var, width=8) \
            .grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=3)
        return row + 1

    def _add_combo(self, box, row, label, var, values):
        ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Combobox(box, textvariable=var, values=values, state="readonly", width=14) \
            .grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=3)
        return row + 1

    def _build_actions(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent)
        bar.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        bar.columnconfigure(1, weight=1)

        ttk.Button(bar, text="New", command=self.reset, width=8).grid(row=0, column=0, sticky="w")
        self.btn_generate = ttk.Button(bar, text="Generate", command=self.generate_async)
        self.btn_generate.grid(row=0, column=1, sticky="ew", padx=8)
        self.btn_save = ttk.Button(bar, text="Save As…", command=self.save_as, state="disabled",
                                   width=10)
        self.btn_save.grid(row=0, column=2, sticky="e")

    def _build_preview(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="Preview", padding=10)
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)

        self.canvas = tk.Label(box, background="#f0f0f0", anchor="center",
                               text="No code yet", foreground="#808080")
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.lbl_details = ttk.Label(box, text="", justify="center", foreground="#505050")
        self.lbl_details.grid(row=1, column=0, sticky="ew", pady=(10, 0))

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, padding=(14, 6))
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.columnconfigure(0, weight=1)
        ttk.Label(bar, textvariable=self.var_status, anchor="w").grid(row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=120)
        self.progress.grid(row=0, column=1, sticky="e")
        self.progress.grid_remove()

    # ----------------------------------------------------------------- azioni

    def _profile_name(self) -> str:
        """Nome interno del profilo scelto (l'elenco mostra le etichette inglesi)."""
        return PROFILE_NAMES.get(self.var_profile.get(), self.var_profile.get())

    def _sync_profile(self) -> None:
        name = self._profile_name()
        preset = PROFILES.get(name)
        if preset:
            self.var_margin.set(preset["margin"])
            self.var_min_version.set(preset["min_version"])
        if hasattr(self, "lbl_hint"):
            self.lbl_hint.configure(text=PROFILE_HINTS.get(name, ""))

    def _colour_field(self, parent: ttk.Frame, label: str, var: tk.StringVar) -> tk.Frame:
        """Pulsante piu' riquadro del colore corrente."""
        holder = ttk.Frame(parent)
        holder.pack(side="left", padx=(0, 12))
        swatch = tk.Frame(holder, width=22, height=22, relief="solid", borderwidth=1)
        swatch.pack(side="left", padx=(0, 5))
        swatch.pack_propagate(False)
        ttk.Button(holder, text=label, width=7,
                   command=lambda: self._pick_colour(var, swatch)).pack(side="left")
        self._paint_swatch(swatch, var.get())
        return swatch

    def _paint_swatch(self, swatch: tk.Frame, colour: str) -> None:
        try:
            swatch.configure(background=colour)
        except tk.TclError:
            pass

    def _pick_colour(self, var: tk.StringVar, swatch: tk.Frame) -> None:
        chosen = colorchooser.askcolor(color=var.get(), title="Pick a colour")
        if chosen and chosen[1]:
            var.set(chosen[1])
            self._paint_swatch(swatch, chosen[1])

    def choose_image(self) -> None:
        path = filedialog.askopenfilename(title="Choose an image", filetypes=IMAGE_TYPES)
        if path:
            self.var_image.set(path)
            self.var_status.set(f"Image: {Path(path).name}")

    def reset(self) -> None:
        self._build_variables_reset()
        self.result = None
        self.preview_image = None
        self.canvas.configure(image="", text="No code yet")
        self.lbl_details.configure(text="")
        self.btn_save.state(["disabled"])
        self.var_status.set("Choose an image and enter the text, then press Generate.")

    def _build_variables_reset(self) -> None:
        d = Settings()
        self.var_image.set("")
        self.var_text.set("https://example.com")
        self.var_profile.set(PROFILE_LABELS["equilibrato"])
        self.var_scale.set(d.scale)
        self.var_method.set(d.method)
        self.var_error.set(d.error)
        self.var_contrast.set(d.contrast)
        self.var_clahe.set(d.clahe)
        self.var_sharpen.set(d.sharpen)
        self.var_zoom.set(d.zoom)
        self.var_focus.set(d.focus)
        self.var_quiet.set(d.quiet)
        self.var_dark.set(d.dark)
        self.var_light.set(d.light)
        self._paint_swatch(self.sw_dark, d.dark)
        self._paint_swatch(self.sw_light, d.light)
        self._sync_profile()

    # ------------------------------------------------------------ generazione

    def generate_async(self) -> None:
        if self.busy:
            return
        image = self.var_image.get().strip()
        text = self.var_text.get()
        if not image:
            messagebox.showwarning("Missing image", "Choose a source image first.")
            return
        if not Path(image).is_file():
            messagebox.showerror("Image not found", f"No such file:\n{image}")
            return
        if not text:
            messagebox.showwarning("Missing text", "Enter the text or URL to encode.")
            return

        try:
            cfg = self._settings()
        except tk.TclError:
            messagebox.showerror("Invalid value", "One of the parameters is not a number.")
            return

        self.busy = True
        self.btn_generate.state(["disabled"])
        self.var_status.set("Generating…")
        self.progress.grid()
        self.progress.start(12)

        verify_it = self.var_verify.get()
        target = PROFILES.get(self._profile_name(), {}).get("target", 0.9)
        threading.Thread(
            target=self._worker, args=(text, Path(image), cfg, verify_it, target), daemon=True
        ).start()

    def _worker(self, text, image, cfg, verify_it, target) -> None:
        """Gira fuori dal thread grafico: qui non si tocca alcun widget."""
        warnings: list[str] = []
        try:
            if verify_it:
                result = generate_verified(text, image, cfg, target_score=target,
                                           quiet=True, warn=warnings.append)
            else:
                result = generate(text, image, cfg, warn=warnings.append)
            self.jobs.put(("ok", result, warnings))
        except Exception as exc:                      # noqa: BLE001 - riportato all'utente
            self.jobs.put(("error", exc, traceback.format_exc()))

    def _drain_jobs(self) -> None:
        try:
            while True:
                kind, payload, extra = self.jobs.get_nowait()
                if kind == "ok":
                    self._on_result(payload, extra)
                else:
                    self._on_error(payload, extra)
        except queue.Empty:
            pass
        self.after(80, self._drain_jobs)

    def _on_result(self, result, warnings: list[str]) -> None:
        self.busy = False
        self.progress.stop()
        self.progress.grid_remove()
        self.btn_generate.state(["!disabled"])
        self.result = result
        self.btn_save.state(["!disabled"])
        self._show_preview(result.image)

        details = (f"Version {result.version} · {result.modules} modules · "
                   f"mask {result.mask} · ECC {result.settings.error}\n"
                   f"Image fidelity {result.fidelity:.2f} · margin {result.settings.margin:.2f}")
        if result.report:
            details += f"\nReadability {result.report.score:.0%} ({result.report.passed}/{result.report.total} tests)"
        self.lbl_details.configure(text=details)

        if result.report and result.report.score < 1.0:
            failed = ", ".join(result.report.failures)
            status = f"Done — readability {result.report.score:.0%}; failed: {failed}"
        elif result.report:
            status = "Done — readable in every test condition."
        else:
            status = "Done — readability not verified."
        if warnings:
            status += "  |  " + "; ".join(WARNINGS.get(w, w) for w in warnings)
        self.var_status.set(status)

    def _on_error(self, exc: Exception, tb: str) -> None:
        self.busy = False
        self.progress.stop()
        self.progress.grid_remove()
        self.btn_generate.state(["!disabled"])
        self.var_status.set(f"Failed: {exc}")
        print(tb, file=sys.stderr)
        messagebox.showerror("Generation failed", str(exc))

    def _show_preview(self, image: Image.Image) -> None:
        preview = image.copy()
        preview.thumbnail((PREVIEW_MAX, PREVIEW_MAX), Image.LANCZOS)
        self.preview_image = ImageTk.PhotoImage(preview)
        self.canvas.configure(image=self.preview_image, text="")

    # ------------------------------------------------------------ salvataggio

    def save_as(self) -> None:
        if self.result is None:
            return
        suggested = "qr.png"
        source = self.var_image.get().strip()
        if source:
            suggested = f"{Path(source).stem}-qr.png"

        path = filedialog.asksaveasfilename(
            title="Save QR code",
            defaultextension=".png",
            initialfile=suggested,
            filetypes=SAVE_TYPES,
        )
        if not path:
            return
        try:
            image = self.result.image
            # JPEG non ha canale alfa e non ammette la modalita' RGBA.
            if Path(path).suffix.lower() in (".jpg", ".jpeg"):
                image = image.convert("RGB")
            image.save(path)
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self.var_status.set(f"Saved to {path}")


def main() -> int:
    try:
        app = App()
    except tk.TclError as exc:
        # Tipico di SSH, container e macchine senza sessione grafica: Tkinter
        # c'e' ma non trova a chi parlare. L'errore di Tcl da solo non lo
        # spiegherebbe a nessuno.
        print(
            f"Could not open a window: {exc}\n"
            "There is no graphical display available on this machine.\n"
            "Use the web interface instead:  python webgui.py --open",
            file=sys.stderr,
        )
        return 1
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
