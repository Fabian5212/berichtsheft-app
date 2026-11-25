# Baut die Desktop-App als einzelne EXE (dist\Berichtsheft-Assistent.exe).
# Aufruf:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Erstelle virtuelle Umgebung (.venv) ..."
    py -3.12 -m venv .venv
}
$py = ".venv\Scripts\python.exe"
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "pip install fehlgeschlagen" }

Write-Host "Tests ..."
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests fehlgeschlagen - kein Build" }

Write-Host "PyInstaller ..."
& $py -m PyInstaller --noconfirm --clean berichtsheft.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fehlgeschlagen" }

Write-Host ""
Write-Host "Fertig: dist\Berichtsheft-Assistent.exe" -ForegroundColor Green
