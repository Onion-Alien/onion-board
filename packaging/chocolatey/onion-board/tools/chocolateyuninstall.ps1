$ErrorActionPreference = 'Stop'

# A silent uninstall skips the "Also remove VB-Cable?" question and leaves the cable;
# sounds and settings in %APPDATA%\OnionBoard are kept.
$packageArgs = @{
  packageName    = $env:ChocolateyPackageName
  softwareName   = 'Onion Board*'
  fileType       = 'exe'
  silentArgs     = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
  validExitCodes = @(0)
}

[array]$key = Get-UninstallRegistryKey -SoftwareName $packageArgs['softwareName']

if ($key.Count -eq 1) {
  $packageArgs['file'] = ($key[0].UninstallString -replace '"', '')
  Uninstall-ChocolateyPackage @packageArgs
} elseif ($key.Count -eq 0) {
  Write-Warning "$($packageArgs['packageName']) has already been uninstalled by other means."
} else {
  Write-Warning "$($key.Count) matches found for '$($packageArgs['softwareName'])'; uninstall it from Windows Settings > Apps."
  $key | ForEach-Object { Write-Warning "- $($_.DisplayName)" }
}
