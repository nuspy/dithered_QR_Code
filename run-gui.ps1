<#
.SYNOPSIS
    Opens the Dithered QR interface on Windows.

.DESCRIPTION
    Uses the project's virtual environment if it exists, otherwise the Python on
    PATH. Starts the desktop window; falls back to the local web interface when
    Tkinter is missing.

.PARAMETER Web
    Use the browser interface instead of the desktop window.

.PARAMETER Port
    Port for the web interface (default 8765).

.EXAMPLE
    .\run-gui.ps1
.EXAMPLE
    .\run-gui.ps1 -Web
#>
[CmdletBinding()]
param(
    [switch]$Web,
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectDir = $PSScriptRoot
$VenvPython = Join-Path $ProjectDir '.venv\Scripts\python.exe'

if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $found = Get-Command py, python3, python -ErrorAction SilentlyContinue |
             Where-Object { $_.Source -notlike '*WindowsApps*' } |
             Select-Object -First 1
    if (-not $found) {
        Write-Host "Python was not found. Run .\install.ps1 first." -ForegroundColor Red
        exit 1
    }
    $Python = $found.Source
    Write-Host "No .venv found, using $Python (run .\install.ps1 to set one up)." -ForegroundColor Yellow
}

Push-Location $ProjectDir
try {
    if ($Web) {
        Write-Host "Starting the web interface on http://127.0.0.1:$Port" -ForegroundColor Cyan
        & $Python webgui.py --port $Port --open
        exit $LASTEXITCODE
    }

    # Tkinter e' nella libreria standard, ma in certe installazioni ridotte
    # manca: meglio accorgersene qui che con una traccia di errore.
    & $Python -c "import tkinter" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Tkinter is not available; opening the web interface instead." -ForegroundColor Yellow
        & $Python webgui.py --port $Port --open
        exit $LASTEXITCODE
    }

    & $Python gui.py
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
