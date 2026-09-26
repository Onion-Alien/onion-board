# Builds a self-contained Soundboard for PCs without Python:
#   dist\Soundboard\Soundboard.exe  (one folder)
#   dist\SoundboardSetup.exe          (the one file to give people: installs the app,
#                                      the virtual cable and the shortcuts)
#
# The installer step needs Inno Setup 6 once:  winget install JRSoftware.InnoSetup
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

# ---- the installer
& $py make_bunny.py   # installer side-panel art (the mascot)
if ($LASTEXITCODE -ne 0) { throw "make_bunny.py failed" }
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Host "Inno Setup 6 not found, so no SoundboardSetup.exe this time." -ForegroundColor Yellow
    Write-Host "Install it with:  winget install JRSoftware.InnoSetup" -ForegroundColor Yellow
    exit 0
}
$version = & $py -c "import soundboard; print(soundboard.__version__)"
& $iscc /Q "/DAppVersion=$version" installer\Soundboard.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "Built dist\SoundboardSetup.exe - that's the one file to give people." -ForegroundColor Green
