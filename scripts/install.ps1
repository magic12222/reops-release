param([switch]$Model)
$ErrorActionPreference = 'Stop'
$reopsRoot = Split-Path $PSScriptRoot
Push-Location $reopsRoot
try {
    if (!(Test-Path -LiteralPath '.venv-nexent\Scripts\python.exe')) {
        & py -3.11 -m venv .venv-nexent
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 virtual environment creation failed.' }
    }
    & .\.venv-nexent\Scripts\python.exe -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    if ($Model) {
        & .\.venv-nexent\Scripts\python.exe -m pip install -r requirements-nexent.txt
        if ($LASTEXITCODE -ne 0) { throw 'Nexent SDK installation failed.' }
    }
    & pnpm --dir web install --frozen-lockfile --store-dir (Join-Path $reopsRoot '.pnpm-store')
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    & pnpm --dir web run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    Write-Host 'Installation complete. See README.md for the startup order.'
} finally { Pop-Location }
