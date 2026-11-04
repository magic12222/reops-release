param(
  [string]$Studio = $env:REOPS_DEVECO_HOME,
  [ValidateSet('default', 'contractTest')][string]$Product = 'default'
)
$ErrorActionPreference = 'Stop'
if (-not $Studio) { $Studio = 'D:\DevTools\Huawei\DevEcoStudio' }
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$NodePath = Join-Path $Studio 'tools\node\node.exe'
$HvigorPath = Join-Path $Studio 'tools\hvigor\bin\hvigorw.js'
if (-not (Test-Path -LiteralPath $NodePath) -or -not (Test-Path -LiteralPath $HvigorPath)) {
  throw '未找到 IDE 配套 Node / Hvigor。用 -Studio 指定 DevEco Studio 安装目录。'
}
$ArtifactDir = Join-Path $ProjectRoot 'artifacts'
New-Item -ItemType Directory -Force -Path $ArtifactDir | Out-Null
$BuildLog = Join-Path $ArtifactDir ('build-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.log')
$EnvKeys = @('JAVA_HOME', 'NODE_HOME', 'DEVECO_SDK_HOME', 'HVIGOR_USER_HOME', 'NPM_CONFIG_CACHE', 'PATH')
$PreviousValues = @{}
foreach ($Key in $EnvKeys) { $PreviousValues[$Key] = [Environment]::GetEnvironmentVariable($Key, 'Process') }
try {
  $env:JAVA_HOME = Join-Path $Studio 'jbr'
  $env:NODE_HOME = Join-Path $Studio 'tools\node'
  $env:DEVECO_SDK_HOME = Join-Path $Studio 'sdk'
  $env:HVIGOR_USER_HOME = Join-Path $ProjectRoot '.cache\hvigor'
  $env:NPM_CONFIG_CACHE = Join-Path $ProjectRoot '.cache\npm'
  $env:PATH = "$env:NODE_HOME;$(Join-Path $Studio 'tools\ohpm\bin');$env:PATH"
  Push-Location -LiteralPath $ProjectRoot
  try {
    & $NodePath $HvigorPath --mode module -p module=entry@default -p "product=$Product" -p buildMode=debug assembleHap --no-daemon --stacktrace 2>&1 | Tee-Object -FilePath $BuildLog
    $BuildExit = $LASTEXITCODE
  } finally { Pop-Location }
} finally {
  foreach ($Key in $EnvKeys) { [Environment]::SetEnvironmentVariable($Key, $PreviousValues[$Key], 'Process') }
}
Write-Host "Hvigor exit=$BuildExit; log=$BuildLog"
exit $BuildExit
