param(
    [string]$QtBin = $(python -c "import PySide6, os; print(os.path.dirname(PySide6.__file__))")
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "Scanning GUI Chinese strings..."
python scripts/scan_gui_i18n.py --mode tr | Out-Null

Write-Host "Generating gallery.th_TH.ts..."
python scripts/generate_gallery_th_ts.py

$lrelease = Join-Path $QtBin "lrelease.exe"
if (-not (Test-Path $lrelease)) {
    throw "lrelease not found at $lrelease. Install PySide6 first."
}

$ts = "src/gui/resource/i18n/gallery.th_TH.ts"
$qm = "src/gui/resource/i18n/gallery.th_TH.qm"
Write-Host "Compiling $qm..."
& $lrelease $ts -qm $qm

$rcc = Join-Path (Split-Path $QtBin) "Scripts\pyside6-rcc.exe"
if (-not (Test-Path $rcc)) {
    throw "pyside6-rcc not found at $rcc. Install PySide6 first."
}
Write-Host "Rebuilding Qt resource bundle..."
& $rcc -g python "src/gui/resource/resource.qrc" -o "src/gui/common/resource.py"
Write-Host "Done."
