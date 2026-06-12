# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: CC0-1.0
#
# WSP_Weighin_build.ps1 — Build der WeighIn-Station als Windows-.exe.
# Das Linux/macOS-Pendant ist WSP_Weighin_build.sh.
#
# WeighIn laeuft als VIER PyInstaller-Binaries, die nebeneinander im selben
# Ordner liegen muessen: der Launcher (main -> "WeighIn.exe") spawnt
# gui.exe / weight.exe / real_scanner.exe aus os.path.dirname(sys.executable).
# Dieses Skript baut alle vier und legt sie in dist\windows\WeighIn\ ab.
#
# Aufruf (PowerShell im WSP-Wurzelordner):
#   .\WSP_Weighin_build.ps1                # setup + build (Default)
#   .\WSP_Weighin_build.ps1 -Stage setup   # nur venv + Abhaengigkeiten
#   .\WSP_Weighin_build.ps1 -Stage build   # nur PyInstaller (venv muss stehen)
#   .\WSP_Weighin_build.ps1 -Stage clean   # dist\ + build\ entfernen
#
# Falls Skripte blockiert sind, einmalig:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

param(
    [ValidateSet('default','setup','build','clean')]
    [string]$Stage = 'default'
)

$ErrorActionPreference = 'Stop'

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$WeighinDir  = Join-Path $ScriptDir 'WeighIn'
$SourcesDir  = Join-Path $WeighinDir 'sources'
$VenvDir     = Join-Path $WeighinDir '.venv-win'
$DistDir     = Join-Path $WeighinDir 'dist\windows'
$BuildDir    = Join-Path $WeighinDir 'build\windows'
$OutDir      = Join-Path $DistDir 'WeighIn'

$LauncherName = 'WeighIn'            # aus main.py
$Components   = @('gui','weight','real_scanner')

$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { 'python' }

function Log  ($m) { Write-Host "[BUILD] $m" -ForegroundColor Cyan }
function Warn ($m) { Write-Host "[WARN]  $m" -ForegroundColor Yellow }
function Fail ($m) { Write-Host "[FAIL]  $m" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $WeighinDir)) { Fail "WeighIn\ nicht neben dem Skript gefunden ($WeighinDir)." }

$VenvPython     = Join-Path $VenvDir 'Scripts\python.exe'
$VenvPyInstall  = Join-Path $VenvDir 'Scripts\pyinstaller.exe'

function Stage-Setup {
    Log "venv unter $VenvDir"
    if (-not (Get-Command $PythonBin -ErrorAction SilentlyContinue)) {
        Fail "Python nicht gefunden. Installiere Python 3.13 (python.org) und setze ggf. PYTHON_BIN."
    }
    if (-not (Test-Path $VenvDir)) { & $PythonBin -m venv $VenvDir }

    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r (Join-Path $WeighinDir 'requirements.txt')

    & $VenvPython -c "import tkinter" 2>$null
    if ($LASTEXITCODE -ne 0) { Warn "tkinter fehlt — Python von python.org inkl. 'tcl/tk' neu installieren." }
    Log "setup fertig"
}

# Gemeinsame PyInstaller-Flags fuer Windows:
#  - pygrabber wird fuer die Kamera-Liste GEBRAUCHT (DirectShow) -> hidden-import.
#  - AVFoundation (macOS) wird ausgeschlossen.
$PyiCommon = @(
    '--noconfirm'
    '--paths',         $SourcesDir
    '--hidden-import', 'pygrabber'
    '--hidden-import', 'pygrabber.dshow_graph'
    '--exclude-module','AVFoundation'
    '--log-level',     'WARN'
)

function Build-Component ($entry, $name, $work) {
    & $VenvPyInstall @PyiCommon `
        --distpath $OutDir `
        --workpath $work `
        --specpath $work `
        --onefile --name $name `
        $entry
    if ($LASTEXITCODE -ne 0) { Fail "PyInstaller fehlgeschlagen fuer $name." }
}

function Stage-Build {
    Log "PyInstaller (4 Komponenten) -> $OutDir"
    if (-not (Test-Path $VenvPyInstall)) { Fail "pyinstaller fehlt — 'setup' erneut laufen lassen." }

    if (Test-Path $DistDir)  { Remove-Item -Recurse -Force $DistDir }
    if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }
    New-Item -ItemType Directory -Force -Path $OutDir   | Out-Null
    New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

    Log "Komponente: $LauncherName (Launcher / main.py)"
    Build-Component (Join-Path $SourcesDir 'main.py') $LauncherName (Join-Path $BuildDir 'main')

    foreach ($comp in $Components) {
        Log "Komponente: $comp"
        Build-Component (Join-Path $SourcesDir "$comp.py") $comp (Join-Path $BuildDir $comp)
    }

    Log "Fertig. Binaries:"
    Get-ChildItem $OutDir -Filter *.exe | ForEach-Object { Write-Host "  $($_.Name)" }
    Log "Start: `"$OutDir\$LauncherName.exe`""
    Warn "Hotkey-Scanner (keyboard-Lib) braucht KEINE Admin-Rechte unter Windows."
    Warn "SmartScreen/Defender koennen unsignierte .exe blocken -> 'Weitere Infos' > 'Trotzdem ausfuehren'."
}

function Stage-Clean {
    Log "Entferne dist\windows, build\windows"
    if (Test-Path $DistDir)  { Remove-Item -Recurse -Force $DistDir }
    if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }
    Log "clean fertig"
}

switch ($Stage) {
    'default' { Stage-Setup; Stage-Build }
    'setup'   { Stage-Setup }
    'build'   { Stage-Build }
    'clean'   { Stage-Clean }
}
