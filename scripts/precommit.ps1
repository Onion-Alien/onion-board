# Every check a commit needs, in one go, on only what you changed:
#   ruff, the sensitive-data scan, the i18n catalogs, and the tests that cover your
#   committed + uncommitted changes since origin/main (scripts/pick_tests.py --local).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\precommit.ps1
#   ... -All      run the whole test suite instead (about 3 minutes)
#   ... -Base X   compare with branch X instead of origin/main
#
# Stops at the first failure. Run from anywhere; it works in the repo root.
param([switch]$All, [string]$Base = "origin/main")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No .venv: see docs/DEVELOPING.md section 1" }
$env:QT_QPA_PLATFORM = "offscreen"

function Step($name, [scriptblock]$cmd) {
    Write-Host "== $name" -ForegroundColor Cyan
    & $cmd
    if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: $name" -ForegroundColor Red; exit 1 }
}

Step "ruff" { & (Join-Path $root ".venv\Scripts\ruff.exe") check . }
Step "sensitive data" { & $py scripts\check_sensitive.py }
# as CI's pick job: every text in every catalog, and every module in docs/CODE.md
Step "translations" { & $py scripts\i18n_extract.py --check }
Step "CODE.md modules" { & $py scripts\check_code_doc.py }

if ($All) { $tests = @("tests") }
else {
    $tests = @(& $py scripts\pick_tests.py $Base --local)
    if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: pick_tests" -ForegroundColor Red; exit 1 }
}
if ($tests.Count -eq 0) { Write-Host "== no tests cover these changes"; exit 0 }
Step "pytest ($($tests -join ' '))" { & $py -m pytest -q @tests }
Write-Host "All checks passed." -ForegroundColor Green
