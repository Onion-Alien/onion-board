# One-shot setup for Soundboard on a fresh Windows PC:
#   1. finds Python 3.12+ (offers to install it with winget if missing)
#   2. creates .venv and installs the Python packages
#   3. adds Desktop + Start menu shortcuts
#   4. offers to install the free virtual cable (VB-Cable)
#
# Run it by double-clicking install.bat.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Ask($q) {
    $a = Read-Host "$q [Y/n]"
    return ($a -eq "" -or $a -match "^[yY]")
}

Write-Host "=== Soundboard setup ===" -ForegroundColor Cyan

# ---- 1. Python
function Find-Python {
    # prefer well-supported versions; brand-new Pythons can lack package wheels
    foreach ($cmd in @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3"), @("python"))) {
        try {
            # (not $cmd[1..0]: for a one-item list that counts backwards and repeats it)
            $exe = $cmd[0]; $rest = @($cmd | Select-Object -Skip 1)
            $v = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v -and [version]$v -ge [version]"3.12") {
                return @{ exe = $exe; args = $rest; version = $v }
            }
        } catch { }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "Python 3.12 or newer is needed." -ForegroundColor Yellow
    if ((Get-Command winget -ErrorAction SilentlyContinue) -and (Ask "Install Python 3.13 with winget now?")) {
        winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [Environment]::GetEnvironmentVariable("Path", "User")
        $py = Find-Python
    }
    if (-not $py) {
        Write-Host "Install Python from https://www.python.org/downloads/ (tick 'Add to PATH'), then run this again." -ForegroundColor Red
        Read-Host "Press Enter to close" | Out-Null
        exit 1
    }
}
Write-Host "Using Python $($py.version)" -ForegroundColor Green

# ---- 2. venv + packages
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Creating virtual environment..."
    & $py.exe @($py.args) -m venv (Join-Path $root ".venv")
}
Write-Host "Installing packages (first time takes a minute)..."
& $venvPy -m pip install --disable-pip-version-check -q -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "Package install failed - see the errors above." -ForegroundColor Red
    Read-Host "Press Enter to close" | Out-Null
    exit 1
}

# ---- 3. shortcuts
$ws = New-Object -ComObject WScript.Shell
$targets = @([Environment]::GetFolderPath("Desktop"),
             (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))
foreach ($dir in $targets) {
    $lnk = $ws.CreateShortcut((Join-Path $dir "Soundboard.lnk"))
    $lnk.TargetPath = Join-Path $root ".venv\Scripts\pythonw.exe"
    $lnk.Arguments = "`"$(Join-Path $root 'main.py')`""
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = Join-Path $root "soundboard.ico"
    $lnk.Description = "Soundboard"
    $lnk.Save()
}
Write-Host "Shortcuts added to the Desktop and Start menu." -ForegroundColor Green

# ---- 4. virtual cable
$cable = Get-CimInstance Win32_SoundDevice -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match "VB-Audio|Virtual Cable|Voicemeeter" }
if ($cable) {
    Write-Host "Virtual cable found: $(($cable | Select-Object -First 1).Name)" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "No virtual cable found. It's what lets Discord / games hear your sounds." -ForegroundColor Yellow
    if (Ask "Install VB-Cable (free, from vb-audio.com) now?") {
        & (Join-Path $root "install-vbcable.ps1")
    } else {
        Write-Host "No problem - the app has an Install button for it too."
    }
}

# ---- optional: ffmpeg for m4a/aac/video
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "Optional: ffmpeg isn't installed. mp3/wav/ogg/flac work without it;" -ForegroundColor DarkGray
    Write-Host "for m4a/aac/video files run:  winget install Gyan.FFmpeg.Essentials" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "All set! Open Soundboard from the Desktop shortcut." -ForegroundColor Cyan
if (Ask "Start it now?") {
    Start-Process (Join-Path $root ".venv\Scripts\pythonw.exe") -ArgumentList "`"$(Join-Path $root 'main.py')`"" -WorkingDirectory $root
}
