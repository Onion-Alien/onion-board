# Rebuild PyInstaller with a bootloader compiled on this PC, and install it into .venv.
#
# The bootloader PyInstaller ships from PyPI is the same file in thousands of programs,
# some of them malware, so machine-learning virus scanners distrust it: the mic helper
# (obmichelper.exe) built with it got "Malicious" (APEX) and "BehavesLike.Win64.Backdoor"
# (Skyhigh) on VirusTotal, false positives. build.ps1 runs this when the stock one is
# installed, and scripts\build_michelper.py refuses to build with it.
#
# Needs MinGW-w64's gcc, the same one the mic effect needs:
#   winget install BrechtSanders.WinLibs.POSIX.UCRT
# Run:  powershell -ExecutionPolicy Bypass -File scripts\build_bootloader.ps1 [-Python <python.exe>]
param([string]$Python)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot)
$py = if ($Python) { $Python } else { ".venv\Scripts\python.exe" }
$version = (Select-String -Path requirements-dev.txt -Pattern "^pyinstaller==(.+)$").Matches[0].Groups[1].Value

if (-not (Get-Command gcc -ErrorAction SilentlyContinue)) {
    $gcc = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter gcc.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $gcc) { throw "No gcc: winget install BrechtSanders.WinLibs.POSIX.UCRT" }
    $env:PATH = "$($gcc.DirectoryName);$env:PATH"
}
$wheels = "build\pyinstaller-wheel"
New-Item -ItemType Directory -Force $wheels | Out-Null
Remove-Item "$wheels\*.whl" -ErrorAction SilentlyContinue
$env:PYINSTALLER_COMPILE_BOOTLOADER = "1"
$env:PYINSTALLER_BOOTLOADER_WAF_ARGS = "--gcc"
& $py -m pip wheel --no-binary pyinstaller --no-deps --no-cache-dir -w $wheels "pyinstaller==$version"
if ($LASTEXITCODE -ne 0) { throw "building PyInstaller $version failed" }
& $py -m pip install --force-reinstall --no-deps (Get-ChildItem "$wheels\*.whl" | Select-Object -First 1).FullName
if ($LASTEXITCODE -ne 0) { throw "installing the rebuilt PyInstaller failed" }
Write-Host "PyInstaller $version with a bootloader compiled here is installed." -ForegroundColor Green
