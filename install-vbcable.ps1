# Installs VB-Audio Virtual Cable (free, donationware) from the official VB-Audio site.
#
# The driver isn't bundled in this repo: VB-Audio's licence doesn't allow redistributing
# it, so this script downloads the current pack from vb-audio.com, checks the setup
# program is really signed by VB-Audio, then runs it (Windows will ask for admin).
#
# VB-Audio says to restart after installing. Often the cable works straight away, so
# this checks instead of always asking: once setup has run it waits for the CABLE
# devices to come up healthy, and if Windows reports they need a restart (problem
# code 14) or they never appear, it exits 3010 (the standard "restart required"
# code) and leaves a marker the app reads until the PC has restarted. Never install
# over a cable that's waiting for a restart; VB-Audio wants a reboot between.
#
# Usage:  powershell -ExecutionPolicy Bypass -File install-vbcable.ps1 [-Silent] [-Check]
#   exit 0 = cable working, 3010 = restart needed, 1 = failed / cancelled,
#   2 = (-Check only) no cable installed
param([switch]$Silent, [switch]$Check)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest much faster

function Pause-Exit($code) {
    if (-not $Silent) { Read-Host "`nPress Enter to close" | Out-Null }
    exit $code
}

$marker = Join-Path $env:APPDATA "Soundboard\cable-restart-pending"

# "ok": driver and its CABLE endpoints present and healthy. "restart": the driver is
# there but Windows hasn't finished with it. "missing": nothing installed.
function Get-CableState {
    $devs = @(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "VB-Audio|Virtual Cable" })
    if (-not $devs) { return "missing" }
    if ($devs | Where-Object { $_.ConfigManagerErrorCode -eq 14 }) { return "restart" }
    $endpoints = @($devs | Where-Object { $_.PNPClass -eq "AudioEndpoint" -and
                                           $_.ConfigManagerErrorCode -eq 0 })
    if (-not $endpoints) { return "restart" }
    return "ok"
}

function Exit-NeedsRestart {
    New-Item -ItemType Directory -Force -Path (Split-Path $marker) | Out-Null
    Set-Content -Path $marker -Value (Get-Date -Format o) -Encoding ascii
    Write-Host ""
    Write-Host "The virtual cable is installed. Windows needs a RESTART to finish" -ForegroundColor Yellow
    Write-Host "setting it up: restart your PC, then open Soundboard again." -ForegroundColor Yellow
    Pause-Exit 3010
}

if ($Check) {
    switch (Get-CableState) { "ok" { exit 0 } "restart" { exit 3010 } default { exit 2 } }
}

Write-Host "=== Virtual cable setup ===" -ForegroundColor Cyan

# Already installed?
switch (Get-CableState) {
    "ok" {
        Remove-Item $marker -ErrorAction SilentlyContinue
        Write-Host "A virtual cable is already installed and working." -ForegroundColor Green
        Pause-Exit 0
    }
    "restart" { Exit-NeedsRestart }
}

# Find the newest Windows driver pack linked from the official page.
$page = "https://vb-audio.com/Cable/"
$zipUrl = $null
try {
    $html = (Invoke-WebRequest -Uri $page -UseBasicParsing).Content
    $packs = [regex]::Matches($html, 'https://download\.vb-audio\.com/Download_CABLE/VBCABLE_Driver_Pack(\d+)\.zip') |
        Sort-Object { [int]$_.Groups[1].Value } -Descending
    if ($packs.Count -gt 0) { $zipUrl = $packs[0].Value }
} catch {
    Write-Host "Couldn't read $page ($($_.Exception.Message))" -ForegroundColor Yellow
}
if (-not $zipUrl) { $zipUrl = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip" }

$work = Join-Path $env:TEMP "vbcable-setup"
Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $work | Out-Null
$zip = Join-Path $work "vbcable.zip"

Write-Host "Downloading $zipUrl"
try {
    Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing
} catch {
    Write-Host "Download failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Opening the download page instead - install it from there." -ForegroundColor Yellow
    Start-Process $page
    Pause-Exit 1
}
Expand-Archive -Path $zip -DestinationPath $work -Force

$exeName = if ([Environment]::Is64BitOperatingSystem) { "VBCABLE_Setup_x64.exe" } else { "VBCABLE_Setup.exe" }
$exe = Get-ChildItem -Path $work -Recurse -Filter $exeName | Select-Object -First 1
if (-not $exe) {
    Write-Host "Setup program $exeName not found in the pack." -ForegroundColor Red
    Pause-Exit 1
}

# Only run it if it's genuinely signed by VB-Audio.
$sig = Get-AuthenticodeSignature -FilePath $exe.FullName
$signer = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { "" }
if ($sig.Status -ne "Valid" -or $signer -notmatch "VB-Audio|Burel") {
    Write-Host "Signature check FAILED ($($sig.Status); signer: $signer). Not running it." -ForegroundColor Red
    Pause-Exit 1
}
Write-Host "Signature OK: $signer" -ForegroundColor Green

Write-Host ""
Write-Host "Starting the installer. Click YES on the Windows prompt," -ForegroundColor Cyan
if (-not $Silent) { Write-Host "then click 'Install Driver' in the VB-Cable window." -ForegroundColor Cyan }
try {
    if ($Silent) {
        Start-Process -FilePath $exe.FullName -ArgumentList "-i", "-h" -Verb RunAs -Wait
    } else {
        Start-Process -FilePath $exe.FullName -Verb RunAs -Wait
    }
} catch {
    Write-Host "Install was cancelled." -ForegroundColor Yellow
    Pause-Exit 1
}

# Setup returns before Windows has finished bringing the devices up; give it a moment.
Write-Host "Checking the cable..."
$state = "missing"
for ($i = 0; $i -lt 10; $i++) {
    $state = Get-CableState
    if ($state -eq "ok") { break }
    Start-Sleep -Seconds 2
}
if ($state -eq "ok") {
    Remove-Item $marker -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "Done - the virtual cable is working. No restart needed." -ForegroundColor Green
    Pause-Exit 0
}
if ($state -eq "missing" -and -not $Silent) {
    # interactive setup closed without clicking "Install Driver"
    Write-Host "The cable didn't get installed. Run this again and click 'Install Driver'." -ForegroundColor Yellow
    Pause-Exit 1
}
Exit-NeedsRestart
