# Export verified relational links before any Neo4j write; preserve Docker volumes.
param()

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
$passwordLine = @(Get-Content -LiteralPath '.env' | Where-Object {
    $_ -match '^PROCUREGRAPH_DB_PASSWORD=.+$'
})
if ($passwordLine.Count -ne 1) { throw 'Expected one database password in .env' }
$env:PROCUREGRAPH_DB_PASSWORD = $passwordLine[0].Substring('PROCUREGRAPH_DB_PASSWORD='.Length)

if ((docker info --format '{{.OSType}}').Trim() -ne 'linux') {
    throw 'Start Docker Desktop with the Linux engine.'
}
$pgStarted = $false
try {
    docker compose -p procuregraph-demo up -d postgres
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL could not start' }
    $pgStarted = $true
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        docker compose -p procuregraph-demo exec -T postgres `
            pg_isready -h 127.0.0.1 -U postgres -d procuregraph | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'PostgreSQL did not become ready' }
    $address = docker compose -p procuregraph-demo port postgres 5432
    if ($LASTEXITCODE -ne 0 -or $address -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw "Unexpected PostgreSQL address: $address"
    }
    $env:PROCUREGRAPH_DB_PORT = $Matches[1]
    & $python -m datasets.generator.export_graph_manifest
    if ($LASTEXITCODE -ne 0) { throw 'Graph manifest export failed' }
    & $python -m datasets.generator.export_graph_manifest
    if ($LASTEXITCODE -ne 0) { throw 'Graph manifest repeat check failed' }
}
finally {
    if ($pgStarted) { docker compose -p procuregraph-demo stop postgres }
}
