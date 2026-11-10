"""Interfaccia web locale, pensata per iPhone e iPad (ma utile ovunque).

Su iOS non esiste Tkinter e non c'e' modo di aprire una finestra nativa da
a-Shell: l'unica superficie grafica disponibile e' Safari. Questo modulo alza un
server sulla sola interfaccia di loopback e serve una pagina che parla con il
generatore. Nessuna dipendenza oltre alla libreria standard e al progetto.

    python3 webgui.py                 poi apri http://127.0.0.1:8765
    python3 webgui.py --port 9000
    python3 webgui.py --open          prova ad aprire il browser da solo

Il server ascolta solo su 127.0.0.1: non e' raggiungibile da altri dispositivi
della rete, ed e' voluto - accetta immagini e scrive file, non e' roba da
esporre. Con --host si puo' cambiare idea, ma sapendo cosa si fa.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import socket
import sys
import threading
import webbrowser
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

import framing
import imaging
from dither import METHODS
from dithered_qr import ERROR_LEVELS, PROFILES, Settings, generate, generate_verified

MAX_UPLOAD = 40 * 1024 * 1024        # 40 MB: una foto di telefono ci sta larga

WARNINGS = {
    framing.FACE_DETECTION_UNAVAILABLE:
        "Face detection unavailable — centred crop. Adjust with Framing and Zoom.",
    framing.NO_FACE_FOUND:
        "No face detected — centred crop. Adjust with Framing and Zoom.",
}
PROFILE_LABELS = {"foto": "Photo first", "equilibrato": "Balanced", "robusto": "Robust"}
PROFILE_HINTS = {
    "foto": "Best-looking image; scan close up and in focus.",
    "equilibrato": "Recognisable photo, readable in every test condition.",
    "robusto": "Easiest to scan: fewer, larger modules. For print and distance.",
}


# --------------------------------------------------------------------------
# pagina
# --------------------------------------------------------------------------

def build_page() -> str:
    profiles = "".join(
        f'<option value="{name}"{" selected" if name == "equilibrato" else ""}>'
        f'{PROFILE_LABELS[name]}</option>'
        for name in PROFILES
    )
    methods = "".join(
        f'<option value="{m}"{" selected" if m == "floyd-steinberg" else ""}>{m}</option>'
        for m in METHODS
    )
    errors = "".join(
        f'<option value="{e}"{" selected" if e == "H" else ""}>{e}</option>'
        for e in ERROR_LEVELS
    )
    presets = json.dumps({n: {**p, "hint": PROFILE_HINTS[n]} for n, p in PROFILES.items()})
    decoders = ", ".join(imaging.decoders()) or "none"
    no_decoder_note = (
        ""
        if imaging.decoders()
        else '<p class="note">No QR decoder installed on this device, so readability '
             'cannot be checked automatically. <strong>Test the code with your camera '
             'before using it.</strong></p>'
    )
    return PAGE.replace("{{PROFILES}}", profiles) \
               .replace("{{METHODS}}", methods) \
               .replace("{{ERRORS}}", errors) \
               .replace("{{PRESETS}}", presets) \
               .replace("{{DECODERS}}", decoders) \
               .replace("{{NO_DECODER}}", no_decoder_note)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>Dithered QR</title>
<style>
:root {
  --bg: #f6f6f7; --card: #ffffff; --ink: #16181d; --muted: #5c6270;
  --line: #d8dade; --accent: #2f6df6; --accent-ink: #ffffff; --warn: #8a5300;
  --radius: 12px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14161a; --card: #1d2026; --ink: #eef0f4; --muted: #a2a9b8;
    --line: #333944; --accent: #5b8dff; --accent-ink: #0b0d11; --warn: #ffc46b;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink); line-height: 1.5;
  font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  padding: env(safe-area-inset-top) env(safe-area-inset-right)
           env(safe-area-inset-bottom) env(safe-area-inset-left);
}
.wrap { max-width: 1100px; margin: 0 auto; padding: 16px 16px 96px; }
h1 { font-size: 1.35rem; margin: 8px 0 4px; }
.sub { color: var(--muted); font-size: .9rem; margin: 0 0 18px; }
.grid { display: grid; gap: 16px; }
@media (min-width: 900px) { .grid { grid-template-columns: 380px 1fr; align-items: start; } }
.card {
  background: var(--card); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 16px;
}
.card h2 { font-size: .8rem; text-transform: uppercase; letter-spacing: .07em;
           color: var(--muted); margin: 0 0 12px; }
label { display: block; font-size: .9rem; margin: 12px 0 5px; }
label:first-of-type { margin-top: 0; }
input[type=text], input[type=file], select {
  width: 100%; min-height: 48px; padding: 10px 12px; font-size: 16px;
  color: var(--ink); background: var(--bg);
  border: 1px solid var(--line); border-radius: 10px;
}
input[type=range] { width: 100%; height: 48px; accent-color: var(--accent); }
input[type=color] { width: 56px; height: 48px; padding: 2px; border: 1px solid var(--line);
                    border-radius: 10px; background: var(--bg); }
.row { display: flex; gap: 12px; align-items: center; }
.row > * { flex: 1; }
.val { flex: 0 0 3.2rem; text-align: right; color: var(--muted);
       font-variant-numeric: tabular-nums; }
.swatches { display: flex; gap: 16px; align-items: center; }
.swatches label { margin: 0 8px 0 0; }
details { margin-top: 14px; border-top: 1px solid var(--line); padding-top: 10px; }
summary { min-height: 48px; display: flex; align-items: center; cursor: pointer;
          font-size: .92rem; color: var(--accent); }
.actions {
  position: fixed; left: 0; right: 0; bottom: 0; display: flex; gap: 10px;
  padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
  background: var(--card); border-top: 1px solid var(--line); z-index: 5;
}
button {
  min-height: 48px; padding: 12px 16px; font-size: 1rem; font-family: inherit;
  border-radius: 10px; border: 1px solid var(--line); background: var(--bg);
  color: var(--ink); cursor: pointer; flex: 1;
}
button.primary { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
button:disabled { opacity: .5; cursor: not-allowed; }
button:focus-visible, input:focus-visible, select:focus-visible, summary:focus-visible {
  outline: 3px solid var(--accent); outline-offset: 2px;
}
#preview { display: grid; place-items: center; min-height: 260px;
           background: var(--bg); border-radius: 10px; padding: 12px; }
#preview img { width: 100%; max-width: 460px; height: auto; image-rendering: pixelated;
               border-radius: 6px; }
.empty { color: var(--muted); font-size: .92rem; }
.details { margin-top: 12px; font-size: .88rem; color: var(--muted); text-align: center; }
.details strong { color: var(--ink); }
.note { color: var(--warn); font-size: .86rem; margin: 12px 0 0; }
.status { margin-top: 12px; font-size: .9rem; min-height: 1.5em; }
.spinner { display: inline-block; width: 15px; height: 15px; margin-right: 8px;
           border: 2px solid var(--line); border-top-color: var(--accent);
           border-radius: 50%; animation: spin .8s linear infinite; vertical-align: -2px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
.saved { overflow-wrap: anywhere; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Dithered QR</h1>
  <p class="sub">A photo, halftoned, that is itself a scannable QR code.
     Decoders available here: {{DECODERS}}.</p>

  <div class="grid">
    <div>
      <div class="card">
        <h2>Source</h2>
        <label for="image">Image</label>
        <input type="file" id="image" accept="image/*">
        <label for="text">Text / URL</label>
        <input type="text" id="text" value="https://example.com" autocapitalize="off"
               autocorrect="off" spellcheck="false" inputmode="url">
      </div>

      <div class="card" style="margin-top:16px">
        <h2>Parameters</h2>
        <label for="profile">Profile</label>
        <select id="profile">{{PROFILES}}</select>
        <p class="sub" id="hint" style="margin:6px 0 0"></p>

        <label for="margin">Margin <span class="sub">— higher is easier to scan</span></label>
        <div class="row">
          <input type="range" id="margin" min="0" max="0.4" step="0.01" value="0.1">
          <span class="val" id="margin-val">0.10</span>
        </div>

        <label for="minVersion">Minimum version</label>
        <div class="row">
          <input type="range" id="minVersion" min="1" max="30" step="1" value="14">
          <span class="val" id="minVersion-val">14</span>
        </div>

        <details>
          <summary>More parameters</summary>

          <label for="scale">Pixels per module</label>
          <div class="row">
            <input type="range" id="scale" min="3" max="17" step="2" value="9">
            <span class="val" id="scale-val">9</span>
          </div>

          <label for="method">Dithering</label>
          <select id="method">{{METHODS}}</select>

          <label for="error">Error correction</label>
          <select id="error">{{ERRORS}}</select>

          <label for="focus">Framing</label>
          <select id="focus">
            <option value="face" selected>face</option>
            <option value="center">center</option>
          </select>

          <label for="quiet">Quiet zone</label>
          <select id="quiet">
            <option value="white" selected>white</option>
            <option value="image">image</option>
          </select>

          <label for="zoom">Zoom</label>
          <div class="row">
            <input type="range" id="zoom" min="0.5" max="3" step="0.1" value="1">
            <span class="val" id="zoom-val">1.0</span>
          </div>

          <label for="contrast">Contrast</label>
          <div class="row">
            <input type="range" id="contrast" min="0.5" max="2.5" step="0.05" value="1.15">
            <span class="val" id="contrast-val">1.15</span>
          </div>

          <label for="clahe">Local contrast</label>
          <div class="row">
            <input type="range" id="clahe" min="0" max="6" step="0.5" value="2">
            <span class="val" id="clahe-val">2.0</span>
          </div>

          <label for="sharpen">Sharpen</label>
          <div class="row">
            <input type="range" id="sharpen" min="0" max="2" step="0.1" value="0.6">
            <span class="val" id="sharpen-val">0.6</span>
          </div>

          <label>Colours</label>
          <div class="swatches">
            <label for="dark">Dark</label><input type="color" id="dark" value="#000000">
            <label for="light">Light</label><input type="color" id="light" value="#ffffff">
          </div>

          <label for="verify" class="row" style="gap:10px; align-items:center">
            <input type="checkbox" id="verify" checked
                   style="flex:0 0 24px; width:24px; height:24px; accent-color:var(--accent)">
            <span style="flex:1">Verify readability (slower)</span>
          </label>
        </details>
        {{NO_DECODER}}
      </div>
    </div>

    <div class="card">
      <h2>Preview</h2>
      <div id="preview"><span class="empty">No code yet.</span></div>
      <div class="details" id="details"></div>
      <div class="status" id="status"></div>
    </div>
  </div>
</div>

<div class="actions">
  <button type="button" id="new">New</button>
  <button type="button" id="generate" class="primary">Generate</button>
  <button type="button" id="save" disabled>Save</button>
</div>

<script>
const PRESETS = {{PRESETS}};
const $ = (id) => document.getElementById(id);
const SLIDERS = {margin: 2, minVersion: 0, scale: 0, zoom: 1, contrast: 2, clahe: 1, sharpen: 1};
let current = null;      // {png: base64, name: string}

for (const [id, digits] of Object.entries(SLIDERS)) {
  const input = $(id), out = $(id + "-val");
  const show = () => out.textContent = Number(input.value).toFixed(digits);
  input.addEventListener("input", show);
  show();
}

function applyProfile() {
  const preset = PRESETS[$("profile").value];
  if (!preset) return;
  $("margin").value = preset.margin;
  $("minVersion").value = preset.min_version;
  $("margin").dispatchEvent(new Event("input"));
  $("minVersion").dispatchEvent(new Event("input"));
  $("hint").textContent = preset.hint || "";
}
$("profile").addEventListener("change", applyProfile);
applyProfile();

function setStatus(text, busy) {
  $("status").innerHTML = (busy ? '<span class="spinner"></span>' : "") +
                          text.replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c]));
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",")[1]);
    reader.onerror = () => reject(new Error("Could not read the file."));
    reader.readAsDataURL(file);
  });
}

$("generate").addEventListener("click", async () => {
  const file = $("image").files[0];
  if (!file) { setStatus("Choose an image first.", false); return; }
  if (!$("text").value) { setStatus("Enter the text or URL to encode.", false); return; }

  $("generate").disabled = true;
  $("save").disabled = true;
  setStatus("Generating… this can take a few seconds.", true);

  try {
    const body = {
      image: await readFile(file),
      text: $("text").value,
      profile: $("profile").value,
      verify: $("verify").checked,
      settings: {
        margin: parseFloat($("margin").value),
        min_version: parseInt($("minVersion").value, 10),
        scale: parseInt($("scale").value, 10),
        method: $("method").value,
        error: $("error").value,
        focus: $("focus").value,
        quiet: $("quiet").value,
        zoom: parseFloat($("zoom").value),
        contrast: parseFloat($("contrast").value),
        clahe: parseFloat($("clahe").value),
        sharpen: parseFloat($("sharpen").value),
        dark: $("dark").value,
        light: $("light").value,
      },
    };
    const response = await fetch("/api/generate", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Generation failed.");

    current = {png: data.png, name: (file.name.replace(/\\.[^.]+$/, "") || "qr") + "-qr.png"};
    $("preview").innerHTML = '<img alt="Generated QR code" src="data:image/png;base64,' +
                             data.png + '">';
    $("details").innerHTML = data.details;
    setStatus(data.status, false);
    $("save").disabled = false;
  } catch (err) {
    setStatus(err.message, false);
  } finally {
    $("generate").disabled = false;
  }
});

$("save").addEventListener("click", async () => {
  if (!current) return;
  const name = prompt("File name", current.name);
  if (!name) return;

  // Il file viene scritto dal server nella cartella del progetto, cosi' su iOS
  // lo si ritrova nell'app File; poi lo si scarica anche dal browser, che su
  // iPhone apre il pannello di condivisione.
  setStatus("Saving…", true);
  try {
    const response = await fetch("/api/save", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({png: current.png, name}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Save failed.");
    setStatus("Saved to " + data.path, false);
    $("status").classList.add("saved");

    const link = document.createElement("a");
    link.href = "data:image/png;base64," + current.png;
    link.download = data.name;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } catch (err) {
    setStatus(err.message, false);
  }
});

$("new").addEventListener("click", () => {
  $("image").value = "";
  $("text").value = "https://example.com";
  $("profile").value = "equilibrato";
  applyProfile();
  current = null;
  $("preview").innerHTML = '<span class="empty">No code yet.</span>';
  $("details").textContent = "";
  $("save").disabled = true;
  setStatus("", false);
});
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# server
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "DitheredQR"
    save_dir = Path.cwd()

    def log_message(self, fmt, *args):        # meno rumore sul terminale
        sys.stderr.write("  %s\n" % (fmt % args))

    # ------------------------------------------------------------------ GET

    def do_GET(self) -> None:
        if self.path.split("?")[0] not in ("/", "/index.html"):
            self._send_json(404, {"error": "not found"})
            return
        page = build_page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(page)

    # ----------------------------------------------------------------- POST

    def do_POST(self) -> None:
        route = self.path.split("?")[0]
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        try:
            if route == "/api/generate":
                self._send_json(200, self._generate(payload))
            elif route == "/api/save":
                self._send_json(200, self._save(payload))
            else:
                self._send_json(404, {"error": "not found"})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:              # noqa: BLE001 - riportato al browser
            self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("empty request")
        if length > MAX_UPLOAD:
            raise ValueError("image too large (40 MB max)")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"malformed request: {exc}") from exc

    # ------------------------------------------------------------ operazioni

    def _generate(self, payload: dict) -> dict:
        text = (payload.get("text") or "").strip()
        if not text:
            raise ValueError("no text to encode")
        raw = payload.get("image")
        if not raw:
            raise ValueError("no image supplied")

        try:
            blob = base64.b64decode(raw, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("the image could not be decoded") from exc

        # Il generatore legge da un percorso: l'immagine caricata viene scritta
        # in un file temporaneo e cancellata subito dopo.
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temp = Path(handle.name)
        try:
            try:
                Image.open(io.BytesIO(blob)).save(temp)
            except OSError as exc:
                raise ValueError("unsupported or damaged image file") from exc

            fields = payload.get("settings") or {}
            allowed = {f for f in Settings.__dataclass_fields__}
            cfg = replace(Settings(), **{k: v for k, v in fields.items() if k in allowed})

            warnings: list[str] = []
            profile = payload.get("profile", "equilibrato")
            target = PROFILES.get(profile, {}).get("target", 0.9)
            if payload.get("verify") and verify_possible():
                result = generate_verified(text, temp, cfg, target_score=target,
                                           quiet=True, warn=warnings.append)
            else:
                result = generate(text, temp, cfg, warn=warnings.append)
        finally:
            temp.unlink(missing_ok=True)

        buffer = io.BytesIO()
        result.image.save(buffer, format="PNG")

        details = (f"Version {result.version} &middot; {result.modules} modules &middot; "
                   f"mask {result.mask} &middot; ECC {result.settings.error}<br>"
                   f"Image fidelity <strong>{result.fidelity:.2f}</strong> &middot; "
                   f"margin {result.settings.margin:.2f}")
        if result.report:
            details += (f"<br>Readability <strong>{result.report.score:.0%}</strong> "
                        f"({result.report.passed}/{result.report.total} tests)")
            if result.report.failures:
                status = (f"Done — readability {result.report.score:.0%}; "
                          f"failed: {', '.join(result.report.failures)}")
            else:
                status = "Done — readable in every test condition."
        else:
            status = "Done — readability not verified. Test the code with your camera."
        if warnings:
            status += "  |  " + "  ".join(WARNINGS.get(w, w) for w in warnings)

        return {
            "png": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "details": details,
            "status": status,
        }

    def _save(self, payload: dict) -> dict:
        raw = payload.get("png")
        if not raw:
            raise ValueError("nothing to save")

        # Solo il nome del file, senza percorso: cosi' non si puo' scrivere
        # fuori dalla cartella scelta all'avvio.
        name = Path(str(payload.get("name") or "qr.png")).name.strip()
        if not name or name.startswith("."):
            raise ValueError("invalid file name")
        if not name.lower().endswith((".png", ".webp", ".bmp", ".jpg", ".jpeg")):
            name += ".png"

        image = Image.open(io.BytesIO(base64.b64decode(raw)))
        if name.lower().endswith((".jpg", ".jpeg")):
            image = image.convert("RGB")
        destination = (self.save_dir / name).resolve()
        if self.save_dir.resolve() not in destination.parents:
            raise ValueError("invalid destination")
        image.save(destination)
        return {"path": str(destination), "name": name}

    # ------------------------------------------------------------- risposte

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def verify_possible() -> bool:
    import verify

    return verify.available()


def pick_port(host: str, port: int) -> int:
    """Se la porta e' occupata si prova la successiva, invece di arrendersi."""
    for candidate in range(port, port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, candidate))
                return candidate
            except OSError:
                continue
    raise SystemExit(f"no free port between {port} and {port + 19}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local web interface for dithered_qr.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1",
                        help="loopback only by default; change it knowingly")
    parser.add_argument("--save-dir", type=Path, default=Path.cwd(),
                        help="where the Save button writes files")
    parser.add_argument("--open", action="store_true", help="open the browser automatically")
    args = parser.parse_args(argv)

    save_dir = args.save_dir.expanduser().resolve()
    save_dir.mkdir(parents=True, exist_ok=True)
    Handler.save_dir = save_dir

    port = pick_port(args.host, args.port)
    url = f"http://{args.host}:{port}"
    server = ThreadingHTTPServer((args.host, port), Handler)

    print("Dithered QR — web interface")
    print(f"  open        {url}")
    print(f"  saves to    {save_dir}")
    print(f"  decoders    {', '.join(imaging.decoders()) or 'none (readability check disabled)'}")
    print(f"  image path  {imaging.backend()}")
    print("  press Ctrl+C to stop")

    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
