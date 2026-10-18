# Builds a self-contained Onion Board for PCs without Python:
#   dist\OnionBoard\OnionBoard.exe  (one folder)
#   dist\OnionBoardSetup.exe          (the one file to give people: installs the app
#                                      and the shortcuts; the virtual cable only if
#                                      its box is ticked)
#
# The installer step needs Inno Setup 6 once:  winget install JRSoftware.InnoSetup
#
# Needs the dev tools once:  .venv\Scripts\pip install -r requirements-dev.txt
# Run:                       powershell -ExecutionPolicy Bypass -File build.ps1
#
# -AppDir / -InstallerDir additionally copy the results somewhere handy, e.g.
#   build.ps1 -AppDir ..\App -InstallerDir ..\Installer
#
# Rebuilds are incremental: PyInstaller keeps its analysis in build\ and reuses it.
#   -Clean        start from scratch (for a release, or if a build acts strangely)
#   -NoInstaller  stop after the app folder; skips the slow Inno Setup compression
param([string]$AppDir, [string]$InstallerDir, [switch]$Clean, [switch]$NoInstaller)
$ErrorActionPreference = "Stop"
# relative to where the caller ran us, not to the repo (we cd into it below); an
# absolute one (E:\out) stays as it is, which Join-Path got wrong
if ($AppDir) { $AppDir = [IO.Path]::GetFullPath([IO.Path]::Combine((Get-Location).Path, $AppDir)) }
if ($InstallerDir) { $InstallerDir = [IO.Path]::GetFullPath([IO.Path]::Combine((Get-Location).Path, $InstallerDir)) }
Set-Location $PSScriptRoot

$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No .venv - run scripts\install.bat first." }

# PyInstaller's stock bootloader is in thousands of programs, some of them malware, so
# virus scanners flag what's built with it (the mic helper got two VirusTotal hits):
# compile one here first (scripts\build_bootloader.ps1, MinGW-w64's gcc), once per .venv.
& $py -c "import sys; sys.path.insert(0, 'scripts'); import build_michelper; sys.exit(bool(build_michelper.stock_bootloader()))"
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller's stock bootloader: compiling one here first" -ForegroundColor Yellow
    & powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_bootloader.ps1 -Python $py
    if ($LASTEXITCODE -ne 0) {
        # Not fatal: fall back to the stock bootloader so a build without MinGW-w64's gcc
        # still works. Such a build may draw antivirus false positives; a release build
        # should install gcc (winget install BrechtSanders.WinLibs.POSIX.UCRT) so this
        # step produces a clean bootloader.
        Write-Warning "scripts\build_bootloader.ps1 failed (is MinGW-w64's gcc installed?): building with PyInstaller's stock bootloader, which may draw antivirus false positives."
    } else {
        $Clean = $true
    }
}
$cleanArg = @()
if ($Clean) { $cleanArg = @("--clean") }
# The .exe's version info: Windows names the app by it (the firewall prompt, Task
# Manager, Properties), so it says "Onion Board" and the real version.
& $py scripts\version_info.py
if ($LASTEXITCODE -ne 0) { throw "version_info.py failed" }
# Of scipy only scipy.fft and scipy.ndimage ship (with the linalg and special they
# import): the app doesn't use scipy, but Onion Watch (the Triggers tab add-on) does
# its FFTs with scipy.fft, and released Onion Watch up to 0.5.6 needs scipy.ndimage
# too: without it their Triggers tab won't load (~1 MB; keep it while anyone may be
# on 0.5.6). scipy's __init__ names every subpackage, so the rest is excluded by name.
# The build's .venv has the dev tools too (requirements-dev.txt), and scipy's test
# helpers import pytest (with pluggy, pygments, colorama...), cffi's compile-only shim
# setuptools: about 600 modules nothing runs. Neither is a runtime need of scipy or cffi;
# an import of one fails as it would on any PC without them.
# Straight into my mic: the Windows audio effect (native\directmic), built with
# MinGW-w64 (winget install BrechtSanders.WinLibs.POSIX.UCRT), bundled as directmic\.
& $py scripts\build_directmic.py
if ($LASTEXITCODE -ne 0) { throw "build_directmic.py failed (is MinGW-w64's g++ installed?)" }
# Its mic helper (soundboard\michelper.py): the admin part alone, frozen with the effect
# DLL, so after the first admin prompt the app sets the effect up without asking.
& $py scripts\build_michelper.py @cleanArg
if ($LASTEXITCODE -ne 0) { throw "build_michelper.py failed" }
# YouTube's player challenge needs a JavaScript engine and most PCs have none: QuickJS,
# fetched from its pinned release and SHA-256-checked (the repo has no binaries),
# bundled as qjs\ with its licence (soundboard\jsengine.py).
& $py scripts\fetch_qjs.py build\qjs
if ($LASTEXITCODE -ne 0) { throw "fetch_qjs.py failed" }
# PyInstaller looks for the DLLs it bundles on PATH too, so a folder there with another
# program's copy (an AI tool's ICU, an older C++ runtime) ends up in the app and Qt
# can't start. Only Windows' own folders while it runs; vc_runtime.py below cleans up
# whatever an older, cached analysis still brings in.
$fullPath = $env:PATH
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\Wbem"
try {
& $py -m PyInstaller --noconfirm @cleanArg --windowed `
    --name OnionBoard --icon assets\onionboard.ico `
    --version-file installer\version_info.txt `
    --add-data "installer\install-vbcable.ps1;." `
    --add-data "assets\onionboard.ico;." `
    --add-data "assets\art;art" `
    --add-data "assets\radio;radio" `
    --add-data "assets\backgrounds;backgrounds" `
    --add-data "assets\lang;lang" `
    --add-binary "build\directmic\obmic.dll;directmic" `
    --add-data "build\michelper\obmichelper;michelper" `
    --add-binary "build\qjs\qjs.exe;qjs" --add-data "build\qjs\LICENSE.txt;qjs" `
    --copy-metadata yt-dlp --collect-all yt_dlp_ejs `
    --collect-all curl_cffi --hidden-import yt_dlp.networking._curlcffi `
    --hidden-import scipy.fft --hidden-import scipy.ndimage `
    --exclude-module scipy.signal `
    --exclude-module scipy.stats --exclude-module scipy.optimize `
    --exclude-module scipy.interpolate --exclude-module scipy.integrate `
    --exclude-module scipy.sparse --exclude-module scipy.spatial `
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtWebChannel --exclude-module PySide6.QtPdf `
    --exclude-module pytest --exclude-module _pytest --exclude-module pluggy `
    --exclude-module iniconfig --exclude-module pygments --exclude-module colorama `
    --exclude-module setuptools --exclude-module _distutils_hack --exclude-module pkg_resources `
    --paths . `
    main.py
} finally { $env:PATH = $fullPath }
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# One C++ runtime: PyInstaller can bundle an older msvcp140.dll from this PC next to
# the newer one PySide6 ships, and if Windows loads the older one Qt can't start ("DLL
# load failed while importing QtWidgets: The specified procedure could not be found").
# It also deletes any bundled ICU DLL (same error): Qt uses Windows' own.
& $py scripts\vc_runtime.py dist\OnionBoard
if ($LASTEXITCODE -ne 0) { throw "vc_runtime.py failed" }
# ...which can swap a runtime DLL in the bundled mic helper too: list its files again,
# as shipped (soundboard\michelper.py install_helper refuses a build that doesn't match)
& $py -c "import sys; from pathlib import Path; sys.path.insert(0, '.'); from soundboard import michelper; michelper.write_manifest(Path(r'dist\OnionBoard\_internal\michelper'))"
if ($LASTEXITCODE -ne 0) { throw "listing the mic helper's files failed" }

# PyInstaller ships all of Qt (QML, 3D, Charts, dev tools, 186 translations...).
# Drop what the app never loads, then prove the trimmed app still starts.
& $py scripts\prune_build.py dist\OnionBoard
if ($LASTEXITCODE -ne 0) { throw "prune_build.py failed" }
& "dist\OnionBoard\OnionBoard.exe" --selftest | Out-Host
if ($LASTEXITCODE -ne 0) { throw "the built app failed its self-test (see above)" }
# The Triggers tab's add-on (Onion Watch) runs on what this build ships: prove it with
# its zip when there is one (ONIONBOARD_ONION_WATCH_ZIP, see docs\DEVELOPING.md).
if ($env:ONIONBOARD_ONION_WATCH_ZIP) {
    & "dist\OnionBoard\OnionBoard.exe" --selftest-addon $env:ONIONBOARD_ONION_WATCH_ZIP | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "the built app can't run the Onion Watch add-on (see above)" }
}

# Add-ons ship with the app (source only; a module's own .venv is made on the user's PC
# by its Install button). modules.py looks for them in the folder next to the exe.
# AI voices don't: they're an optional download (soundboard\aiaddon.py,
# scripts\make_ai_voices_zip.py).
foreach ($m in Get-ChildItem modules -Directory | Where-Object Name -ne "ai-voices") {
    robocopy $m.FullName "dist\OnionBoard\modules\$($m.Name)" /E /XD .venv .python __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "copying module $($m.Name) failed" }
}
$global:LASTEXITCODE = 0

# Licences travel with the binaries (Qt is LGPL; see scripts\make_notices.py)
Copy-Item LICENSE "dist\OnionBoard\LICENSE.txt"
& $py scripts\make_notices.py "dist\OnionBoard\THIRD-PARTY-NOTICES.txt"
if ($LASTEXITCODE -ne 0) { throw "make_notices.py failed" }

function Publish-Build {
    if ($AppDir) {
        # /XD .venv .python: keep an add-on's environment (and its own Python) installed from the app's Voice tab
        robocopy "dist\OnionBoard" $AppDir /MIR /XD .venv .python /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "copying the app to $AppDir failed" }
        Write-Host "Copied the app to $AppDir" -ForegroundColor Green
    }
    # -NoInstaller: dist\ may hold an older installer; don't pass it off as new
    if ($InstallerDir -and -not $NoInstaller -and (Test-Path "dist\OnionBoardSetup.exe")) {
        New-Item -ItemType Directory -Force $InstallerDir | Out-Null
        Copy-Item "dist\OnionBoardSetup.exe" $InstallerDir -Force
        Write-Host "Copied OnionBoardSetup.exe to $InstallerDir" -ForegroundColor Green
    }
    $global:LASTEXITCODE = 0
}

$exe = Join-Path $PSScriptRoot "dist\OnionBoard\OnionBoard.exe"
$size = [math]::Round((Get-ChildItem (Split-Path $exe) -Recurse | Measure-Object Length -Sum).Sum / 1MB)
Write-Host ""
Write-Host "Built $exe ($size MB folder)" -ForegroundColor Green

# ---- the installer
if ($NoInstaller) {
    Publish-Build
    exit 0
}
& $py scripts\pictures\make_bunny.py   # installer side-panel art (the mascot)
if ($LASTEXITCODE -ne 0) { throw "make_bunny.py failed" }
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Host "Inno Setup 6 not found, so no OnionBoardSetup.exe this time." -ForegroundColor Yellow
    Write-Host "Install it with:  winget install JRSoftware.InnoSetup" -ForegroundColor Yellow
    Publish-Build
    exit 0
}
# Files with the same bytes as another (the mic helper's own Python, mostly) go into the
# installer once; every copy still installs where it was. Written now, so the list
# always matches dist\ (installer\OnionBoard.iss includes it).
& $py scripts\installer_dupes.py dist\OnionBoard build\installer
if ($LASTEXITCODE -ne 0) { throw "installer_dupes.py failed" }
$version = & $py -c "import soundboard; print(soundboard.__version__)"
& $iscc /Q "/DAppVersion=$version" installer\OnionBoard.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "Built dist\OnionBoardSetup.exe - that's the one file to give people." -ForegroundColor Green
Publish-Build
