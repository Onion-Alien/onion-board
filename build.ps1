# Builds a self-contained Soundboard for PCs without Python:
#   dist\Soundboard\Soundboard.exe  (one folder; zip it and ship it)
#
# Needs the dev tools once:  .venv\Scripts\pip install -r requirements-dev.txt
# Run:                       powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No .venv - run install.bat first." }

& $py -m PyInstaller --noconfirm --clean --windowed `
    --name Soundboard --icon soundboard.ico `
    --add-data "install-vbcable.ps1;." `
    --add-data "soundboard.ico;." `
    --paths . `
    main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Join-Path $PSScriptRoot "dist\Soundboard\Soundboard.exe"
$size = [math]::Round((Get-ChildItem (Split-Path $exe) -Recurse | Measure-Object Length -Sum).Sum / 1MB)
Write-Host ""
Write-Host "Built $exe ($size MB folder)" -ForegroundColor Green
Write-Host "The virtual cable still has to be installed on the target PC: the app's own" -ForegroundColor DarkGray
Write-Host "'Install the free virtual cable' button handles that." -ForegroundColor DarkGray
