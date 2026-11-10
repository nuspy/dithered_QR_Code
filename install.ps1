<#
.SYNOPSIS
    Installa dithered_qr su Windows: Python (se manca), ambiente virtuale, dipendenze.

.DESCRIPTION
    Lo script e' rieseguibile: se trova gia' l'ambiente lo aggiorna invece di
    ricrearlo. Al termine genera un codice di prova e lo rilegge, cosi' l'esito
    dell'installazione e' verificato e non solo dichiarato.

.PARAMETER SkipPython
    Non tenta di installare Python anche se manca o e' troppo vecchio.

.PARAMETER Minimal
    Installa il solo nucleo (segno, Pillow, numpy), senza OpenCV ne' ZBar.
    Il generatore funziona, ma senza verifica di leggibilita' ne' inquadratura
    automatica sul volto.

.PARAMETER Force
    Ricrea l'ambiente virtuale da zero.

.EXAMPLE
    .\install.ps1
.EXAMPLE
    .\install.ps1 -Minimal
#>
[CmdletBinding()]
param(
    [switch]$SkipPython,
    [switch]$Minimal,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectDir = $PSScriptRoot
$VenvDir    = Join-Path $ProjectDir '.venv'
$MinPython  = [version]'3.10'

function Write-Step  { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok    { param($m) Write-Host "    $m" -ForegroundColor Green }
function Write-Warn2 { param($m) Write-Host "    $m" -ForegroundColor Yellow }
function Write-Info  { param($m) Write-Host "    $m" -ForegroundColor DarkGray }

# --------------------------------------------------------------------------
# 1. Python
# --------------------------------------------------------------------------

function Get-PythonCandidates {
    # 'py' e' il launcher ufficiale e sa elencare le versioni installate;
    # 'python' su Windows puo' essere l'alias del Microsoft Store, che non e'
    # un interprete ma un collegamento allo store: va scartato.
    $found = @()
    foreach ($cmd in @('py', 'python3', 'python')) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        if ($exe.Source -like '*WindowsApps*') { continue }
        $found += $exe.Source
    }
    return $found
}

function Get-PythonVersion {
    param([string]$Exe, [string[]]$Prefix = @())
    try {
        $args = $Prefix + @('-c', 'import sys; print("%d.%d" % sys.version_info[:2])')
        $out = & $Exe @args 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        return [version]($out.Trim())
    } catch { return $null }
}

function Resolve-Python {
    foreach ($exe in Get-PythonCandidates) {
        # Il launcher 'py' va interrogato chiedendo esplicitamente Python 3.
        $prefixes = if ([IO.Path]::GetFileNameWithoutExtension($exe) -eq 'py') { @(@('-3'), @()) } else { @(@()) }
        foreach ($prefix in $prefixes) {
            $ver = Get-PythonVersion -Exe $exe -Prefix $prefix
            if ($ver -and $ver -ge $MinPython) {
                return [pscustomobject]@{ Exe = $exe; Prefix = $prefix; Version = $ver }
            }
        }
    }
    return $null
}

function Install-Python {
    Write-Step "Installazione di Python"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw @"
Python $MinPython o superiore non e' installato e winget non e' disponibile.
Installa Python da https://www.python.org/downloads/ ricordando di spuntare
"Add python.exe to PATH", poi riesegui questo script.
"@
    }
    Write-Info "winget install Python.Python.3.12"
    winget install --id Python.Python.3.12 --source winget `
        --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        throw "winget non e' riuscito a installare Python (codice $LASTEXITCODE)."
    }

    # winget aggiorna il PATH della sessione futura, non di questa: lo rileggiamo.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

Write-Step "Ricerca di Python $MinPython o superiore"
$python = Resolve-Python
if (-not $python) {
    if ($SkipPython) { throw "Python $MinPython+ non trovato e -SkipPython e' attivo." }
    Install-Python
    $python = Resolve-Python
    if (-not $python) {
        throw "Python risulta installato ma non e' raggiungibile. Apri un nuovo terminale e riprova."
    }
}
Write-Ok "Python $($python.Version) -> $($python.Exe)"

# --------------------------------------------------------------------------
# 2. Ambiente virtuale
# --------------------------------------------------------------------------

Write-Step "Ambiente virtuale in .venv"
if ($Force -and (Test-Path $VenvDir)) {
    Write-Info "rimozione dell'ambiente esistente (-Force)"
    Remove-Item $VenvDir -Recurse -Force
}

$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    & $python.Exe @($python.Prefix) -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "Creazione dell'ambiente virtuale non riuscita." }
    Write-Ok "creato"
} else {
    Write-Ok "gia' presente, verra' aggiornato"
}

# --------------------------------------------------------------------------
# 3. Dipendenze
# --------------------------------------------------------------------------

Write-Step "Installazione delle dipendenze"
$reqFile = if ($Minimal) { 'requirements-minimal.txt' } else { 'requirements.txt' }
Write-Info $reqFile

& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r (Join-Path $ProjectDir $reqFile) --quiet
if ($LASTEXITCODE -ne 0) { throw "Installazione delle dipendenze non riuscita." }
Write-Ok "installate"

# --------------------------------------------------------------------------
# 4. Controllo di pyzbar
# --------------------------------------------------------------------------

if (-not $Minimal) {
    Write-Step "Controllo del decoder ZBar"
    & $VenvPython -c "from pyzbar import pyzbar" 2>$null
    if ($LASTEXITCODE -ne 0) {
        # Il wheel di pyzbar porta con se' libzbar, ma quella DLL e' compilata
        # con il runtime Visual C++ 2013: se manca, l'import fallisce.
        Write-Warn2 "pyzbar non si carica: manca quasi certamente il runtime Visual C++ 2013."
        Write-Warn2 "Rimedio:  winget install Microsoft.VCRedist.2013.x64"
        Write-Warn2 "Senza ZBar la verifica usa il solo decoder OpenCV, piu' indulgente."
    } else {
        Write-Ok "ZBar disponibile"
    }
}

# --------------------------------------------------------------------------
# 5. Prova sul campo
# --------------------------------------------------------------------------

Write-Step "Prova di generazione e rilettura"
$probe = @'
import sys, tempfile, os
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, os.getcwd())
import imaging, verify
from dithered_qr import Settings, generate

side = 420
y, x = np.mgrid[0:side, 0:side]
img = 40 + 170 * (y / side)
img[(x - side*0.5)**2 + (y - side*0.45)**2 < (side*0.3)**2] = 230
tmp = Path(tempfile.gettempdir()) / "dqr_probe.png"
Image.fromarray(np.clip(img,0,255).astype("uint8"), "L").save(tmp)

testo = "https://esempio.it/prova"
res = generate(testo, tmp, Settings(min_version=7))
print(f"    backend immagine: {imaging.backend()}")
print(f"    decoder QR:       {', '.join(imaging.decoders()) or 'nessuno'}")
print(f"    simbolo:          versione {res.version}, {res.modules} moduli, fedelta {res.fidelity:.2f}")
if verify.available():
    letto = verify.decode(np.array(res.image.convert("L")))
    if testo not in letto:
        print("    ERRORE: il codice di prova non si rilegge", file=sys.stderr)
        raise SystemExit(1)
    print("    rilettura:        riuscita")
else:
    print("    rilettura:        non verificabile (nessun decoder installato)")

try:
    import tkinter  # noqa: F401
    print("    interfacce:       finestra nativa e pagina web")
except ImportError:
    print("    interfacce:       solo pagina web (Tkinter assente)")
tmp.unlink(missing_ok=True)
'@

Push-Location $ProjectDir
try {
    $probe | & $VenvPython -
    if ($LASTEXITCODE -ne 0) { throw "La prova di generazione non e' riuscita." }
} finally {
    Pop-Location
}

# --------------------------------------------------------------------------

Write-Host ""
Write-Host "Installazione completata." -ForegroundColor Green
Write-Host ""
Write-Host "  Interfaccia grafica:" -ForegroundColor White
Write-Host "    .\run-gui.ps1                finestra nativa"
Write-Host "    .\run-gui.ps1 -Web           pagina web, anche da telefono"
Write-Host ""
Write-Host "  Riga di comando:" -ForegroundColor White
Write-Host "    .\.venv\Scripts\python.exe dithered_qr.py `"https://esempio.it`" foto.jpg -o qr.png"
Write-Host ""
Write-Host "  Oppure attiva l'ambiente una volta sola:" -ForegroundColor White
Write-Host "    .\.venv\Scripts\Activate.ps1"
Write-Host "    python dithered_qr.py `"https://esempio.it`" foto.jpg -o qr.png"
Write-Host ""
Write-Host "  Se Activate.ps1 viene bloccato dai criteri di esecuzione:" -ForegroundColor DarkGray
Write-Host "    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned" -ForegroundColor DarkGray
Write-Host ""
