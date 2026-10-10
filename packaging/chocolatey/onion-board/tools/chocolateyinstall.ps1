$ErrorActionPreference = 'Stop'

$pp = Get-PackageParameters

# Installer tasks: never the VB-Cable driver, FFmpeg or the live voice add-on
# (each downloads more software); Tor and the network log stay at their default (off).
$tasks = @('!vbcable', '!ffmpeg', '!livevoice')
if ($pp['NoDesktopIcon']) { $tasks += '!desktopicon' }

$silentArgs = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /CLOSEAPPLICATIONS " +
              "/MERGETASKS=`"$($tasks -join ',')`" " +
              "/LOG=`"$env:TEMP\$env:ChocolateyPackageName.$env:ChocolateyPackageVersion.Install.log`""
if ($pp['Offline']) { $silentArgs += ' /OFFLINE=1' }

$packageArgs = @{
  packageName    = $env:ChocolateyPackageName
  fileType       = 'exe'
  url64bit       = 'https://github.com/Onion-Alien/onion-board/releases/download/v1.9.27/OnionBoardSetup.exe'
  checksum64     = '6F9AB882FFD07498A9C9876408ADCAC6C45FBEFF0944CD004F9E21F5A0D993D2'
  checksumType64 = 'sha256'
  silentArgs     = $silentArgs
  validExitCodes = @(0)
  softwareName   = 'Onion Board*'
}

Install-ChocolateyPackage @packageArgs
