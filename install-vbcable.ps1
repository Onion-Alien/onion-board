# Installs VB-Audio Virtual Cable (free, donationware) from the official VB-Audio site.
#
# The driver isn't bundled in this repo: VB-Audio's licence doesn't allow redistributing
# it, so this script downloads the current pack from vb-audio.com, checks the setup
# program is really signed by VB-Audio, then runs it (Windows will ask for admin).
#
# Usage:  powershell -ExecutionPolicy Bypass -File install-vbcable.ps1 [-Silent]
param([switch]$Silent)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest much faster

function Pause-Exit($code) {
    if (-not $Silent) { Read-Host "`nPress Enter to close" | Out-Null }
    exit $code
}

Write-Host "=== Virtual cable setup ===" -ForegroundColor Cyan

# Already installed?
$existing = Get-CimInstance Win32_SoundDevice -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match "VB-Audio|Virtual Cable" }
if ($existing) {
    Write-Host "A virtual cable is already installed:" -ForegroundColor Green
    $existing | ForEach-Object { Write-Host "  - $($_.Name)" }
    Pause-Exit 0
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

Write-Host ""
Write-Host "Done. Back in Soundboard, click 'I've installed it - check again'." -ForegroundColor Green
Write-Host "If the cable doesn't show up, restart your PC." -ForegroundColor Green
Pause-Exit 0
