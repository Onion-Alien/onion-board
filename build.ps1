# Builds a self-contained Soundboard for PCs without Python:
#   dist\Soundboard\Soundboard.exe  (one folder)
#   dist\SoundboardSetup.exe          (the one file to give people: installs the app,
#                                      the virtual cable and the shortcuts)
#
# The installer step needs Inno Setup 6 once:  winget install JRSoftware.InnoSetup
#
# Needs the dev tools once:  .venv\Scripts\pip install -r requirements-dev.txt
# Run:                       powershell -ExecutionPolicy Bypass -File build.ps1
#
# -AppDir / -InstallerDir additionally copy the results somewhere handy, e.g.
#   build.ps1 -AppDir ..\App -InstallerDir ..\Installer
param([string]$AppDir, [string]$InstallerDir)
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

# Licences travel with the binaries (Qt is LGPL; see scripts\make_notices.py)
Copy-Item LICENSE "dist\Soundboard\LICENSE.txt"
& $py scripts\make_notices.py "dist\Soundboard\THIRD-PARTY-NOTICES.txt"
if ($LASTEXITCODE -ne 0) { throw "make_notices.py failed" }

function Publish-Build {
    if ($AppDir) {
        robocopy "dist\Soundboard" $AppDir /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "copying the app to $AppDir failed" }
        Write-Host "Copied the app to $AppDir" -ForegroundColor Green
    }
    if ($InstallerDir -and (Test-Path "dist\SoundboardSetup.exe")) {
        New-Item -ItemType Directory -Force $InstallerDir | Out-Null
        Copy-Item "dist\SoundboardSetup.exe" $InstallerDir -Force
        Write-Host "Copied SoundboardSetup.exe to $InstallerDir" -ForegroundColor Green
    }
    $global:LASTEXITCODE = 0
}

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
    Publish-Build
    exit 0
}
$version = & $py -c "import soundboard; print(soundboard.__version__)"
& $iscc /Q "/DAppVersion=$version" installer\Soundboard.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "Built dist\SoundboardSetup.exe - that's the one file to give people." -ForegroundColor Green
Publish-Build
