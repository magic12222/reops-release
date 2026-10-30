param([Parameter(Mandatory=$true)][ValidateSet('sample', 'api', 'monitor', 'web')][string]$Part)
$ErrorActionPreference = 'Stop'
$reopsRoot = Split-Path $PSScriptRoot
Push-Location $reopsRoot
try {
    switch ($Part) {
        'sample' { & pnpm --dir web run preview --port 4173 }
        'api' { & .\.venv-nexent\Scripts\python.exe -m scripts.run_dashboard --skip-history --researchloop-web }
        'monitor' { & .\.venv-nexent\Scripts\python.exe -m scripts.run_vikunja_workbench --serve --paused }
        'web' {
            $env:REOPS_DASHBOARD_PROXY = 'http://127.0.0.1:8020'
            $env:REOPS_WORKBENCH_PROXY = 'http://127.0.0.1:8021'
            & pnpm --dir web run dev --port 5174
        }
    }
    $reopsExitCode = $LASTEXITCODE
} finally { Pop-Location }
exit $reopsExitCode
