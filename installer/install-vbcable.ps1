# Installs VB-Audio Virtual Cable (free, donationware) from the official VB-Audio site.
#
# The driver isn't bundled in this repo: VB-Audio's licence doesn't allow redistributing
# it, so this script downloads the current pack from vb-audio.com, checks the setup
# program is really signed by VB-Audio, then runs it (Windows will ask for admin).
#
# VB-Audio says to restart after installing. Often the cable works straight away, so
# this checks instead of always asking: once setup has run it waits for the CABLE
# devices to come up healthy, and if Windows reports they need a restart (problem
# code 14) or they never appear, it first tries to wake them without one (restart
# the cable devices and the Windows audio services, then wait longer). Only if that
# fails too does it exit 3010 (the standard "restart required" code) and leave a
# marker the app reads until the PC has restarted. Never install over a cable that's
# waiting for a restart; VB-Audio wants a reboot between.
#
# The script elevates itself once (one "Yes" on the Windows prompt) when it has
# something to install or wake; checking a working cable needs no admin.
#
# Usage:  powershell -ExecutionPolicy Bypass -File installer\install-vbcable.ps1 [-Silent] [-Check]
#                    [-StatusFile <path>]
#   exit 0 = cable working, 3010 = restart needed, 1 = failed / cancelled,
#   2 = (-Check only) no cable installed
#   -StatusFile: each step writes "<step>|<text>" there (steps: download, install,
#   wake, check) so the app can show progress.
param([switch]$Silent, [switch]$Check, [string]$StatusFile, [switch]$Elevated)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest much faster

function Pause-Exit($code) {
    if (-not $Silent) { Read-Host "`nPress Enter to close" | Out-Null }
    exit $code
}

function Say($step, $text) {
    Write-Host $text
    if ($StatusFile) {
        try { Set-Content -Path $StatusFile -Value "$step|$text" -Encoding utf8 } catch { }
    }
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

$marker = Join-Path $env:APPDATA "OnionBoard\cable-restart-pending"

# "ok": driver and its CABLE endpoints present and healthy. "restart": the driver is
# there but Windows hasn't finished with it. "missing": nothing installed.
function Get-CableState {
    $devs = @(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "VB-Audio|Virtual Cable" })
    if (-not $devs) { return "missing" }
    if ($devs | Where-Object { $_.ConfigManagerErrorCode -eq 14 }) { return "restart" }
    # just uninstalled: the driver's own device is gone but its CABLE endpoints linger
    # until Windows restarts. Not working, and VB-Audio wants a reboot before reinstalling.
    if (-not ($devs | Where-Object { $_.PNPClass -ne "AudioEndpoint" })) { return "restart" }
    $endpoints = @($devs | Where-Object { $_.PNPClass -eq "AudioEndpoint" -and
                                           $_.ConfigManagerErrorCode -eq 0 })
    if (-not $endpoints) { return "restart" }
    return "ok"
}

function Exit-NeedsRestart {
    New-Item -ItemType Directory -Force -Path (Split-Path $marker) | Out-Null
    Set-Content -Path $marker -Value (Get-Date -Format o) -Encoding ascii
    Say "restart" "The virtual cable is installed, but Windows needs a restart to finish."
    Write-Host ""
    Write-Host "The virtual cable is installed. Windows needs a RESTART to finish" -ForegroundColor Yellow
    Write-Host "setting it up: restart your PC, then open Onion Board again." -ForegroundColor Yellow
    Pause-Exit 3010
}

function Exit-Working {
    Remove-Item $marker -ErrorAction SilentlyContinue
    Say "done" "The virtual cable is working."
    Write-Host ""
    Write-Host "Done - the virtual cable is working. No restart needed." -ForegroundColor Green
    Pause-Exit 0
}

# Setup returns before Windows has finished bringing the devices up, so poll a while.
function Wait-Cable($seconds) {
    $state = Get-CableState
    for ($i = 0; $i -lt $seconds / 2 -and $state -ne "ok"; $i++) {
        Start-Sleep -Seconds 2
        $state = Get-CableState
    }
    return $state
}

# Most cables that "need a restart" start working if their devices and the Windows
# audio services are restarted instead, so try that before asking for a reboot.
# Needs admin. Other sound cuts out for a moment while the audio service restarts.
function Wake-Cable {
    Say "wake" "Waking the cable up (your sound may cut out for a second)..."
    try { & pnputil.exe /scan-devices | Out-Null } catch { }
    # the cable's own devices; its CABLE Input / Output endpoints come back with them
    $devs = @(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "VB-Audio|Virtual Cable" -and $_.PNPClass -ne "AudioEndpoint" })
    foreach ($d in $devs) {
        # /restart-device needs Windows 10 2004 or later; older ones just skip it
        try { & pnputil.exe /restart-device "$($d.DeviceID)" | Out-Null } catch { }
    }
    try {
        Restart-Service -Name AudioEndpointBuilder -Force   # also stops Windows Audio
        Start-Service -Name Audiosrv
    } catch {
        Write-Host "Couldn't restart the audio service: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    Say "check" "Checking the cable..."
    return Wait-Cable 30
}

if ($Check) {
    switch (Get-CableState) { "ok" { exit 0 } "restart" { exit 3010 } default { exit 2 } }
}

Write-Host "=== Virtual cable setup ===" -ForegroundColor Cyan

# Already installed?
$state = Get-CableState
if ($state -eq "ok") {
    Remove-Item $marker -ErrorAction SilentlyContinue
    Say "done" "A virtual cable is already installed and working."
    Pause-Exit 0
}

# Everything past here needs admin: ask once, then carry on as the elevated copy.
if (-not (Test-Admin) -and -not $Elevated) {
    Say "permission" "Waiting for you to click Yes..."
    $argv = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Elevated")
    if ($Silent) { $argv += "-Silent" }
    if ($StatusFile) { $argv += @("-StatusFile", "`"$StatusFile`"") }
    try {
        $p = Start-Process powershell.exe -ArgumentList $argv -Verb RunAs -PassThru -Wait `
            -WindowStyle $(if ($Silent) { "Hidden" } else { "Normal" })
    } catch {
        Say "cancelled" "Install was cancelled."
        Pause-Exit 1
    }
    exit $p.ExitCode   # the elevated copy has already said everything (and paused)
}

if ($state -eq "restart") {
    # installed earlier and still waiting on Windows: wake it, never install over it
    if ((Wake-Cable) -eq "ok") { Exit-Working }
    Exit-NeedsRestart
}

# Find the newest Windows driver pack linked from the official page.
Say "download" "Downloading the virtual cable..."
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

# A fresh folder only admins can write to: this copy runs elevated, and the user's own
# %TEMP% would let any program swap the setup exe (or plant a DLL) before it runs.
$work = Join-Path $env:SystemRoot ("Temp\vbcable-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $work | Out-Null
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
foreach ($sid in "S-1-5-32-544", "S-1-5-18") {   # Administrators, SYSTEM
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
        (New-Object Security.Principal.SecurityIdentifier $sid), "FullControl",
        "ContainerInherit,ObjectInherit", "None", "Allow")))
}
Set-Acl -Path $work -AclObject $acl
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
# the certificate's own name (an EV code-signing cert: VB-Audio's legal entity), not
# just "contains Burel" anywhere in the subject
$cn = if ($sig.SignerCertificate) { $sig.SignerCertificate.GetNameInfo("SimpleName", $false) } else { "" }
if ($sig.Status -ne "Valid" -or $cn -notmatch "^(BUREL VINCENT|VB-Audio)\b") {
    Write-Host "Signature check FAILED ($($sig.Status); signer: $signer). Not running it." -ForegroundColor Red
    Pause-Exit 1
}
Write-Host "Signature OK: $signer" -ForegroundColor Green

Write-Host ""
Say "install" "Installing the virtual cable..."
if (-not $Silent) { Write-Host "Click 'Install Driver' in the VB-Cable window." -ForegroundColor Cyan }
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

Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue

Say "check" "Checking the cable..."
$state = Wait-Cable 20
if ($state -eq "ok") { Exit-Working }
if ($state -eq "missing" -and -not $Silent) {
    # interactive setup closed without clicking "Install Driver"
    Say "cancelled" "The cable didn't get installed."
    Write-Host "The cable didn't get installed. Run this again and click 'Install Driver'." -ForegroundColor Yellow
    Pause-Exit 1
}
if ((Wake-Cable) -eq "ok") { Exit-Working }
Exit-NeedsRestart
