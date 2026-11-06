# Read persisted investigation results with PostgreSQL only; preserve its volume.
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
$running = @(docker ps --format '{{.Names}}')
if ($LASTEXITCODE -ne 0 -or $running -match '^procuregraph-(demo-postgres|storage-minio|graph-neo4j|vector-qdrant)-') {
    throw 'A demo container is running; stop it before this PostgreSQL-only check.'
}
$started = $false
try {
    $started = $true
    docker compose -p procuregraph-demo up -d postgres
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL could not start' }
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
    & $python -m apps.api.app.services.check_investigation_read_api
    if ($LASTEXITCODE -ne 0) { throw 'Private investigation read API check failed' }
}
finally {
    if ($started) { docker compose -p procuregraph-demo stop postgres }
}
