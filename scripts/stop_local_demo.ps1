param()

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

$project = 'procuregraph-demo'
$pidPath = Join-Path (Get-Location).Path '.local-demo.pid'
$portPath = Join-Path (Get-Location).Path '.local-demo.port'

if (Test-Path -LiteralPath $pidPath) {
    $apiPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $apiPid"
    if ($processInfo -and
        $processInfo.CommandLine -match 'uvicorn' -and
        $processInfo.CommandLine -match 'apps\.api\.app\.main:app') {
        Stop-Process -Id $apiPid -Force
    }
    Remove-Item -LiteralPath $pidPath
}
Remove-Item -LiteralPath $portPath -ErrorAction SilentlyContinue

docker compose -p $project stop postgres
if ($LASTEXITCODE -ne 0) { throw 'Could not stop demo PostgreSQL.' }
Write-Output 'PASS: demo stopped; PostgreSQL volume retained.'
