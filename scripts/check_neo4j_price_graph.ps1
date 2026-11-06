# Recheck PostgreSQL, stop it, then import into a separate low-memory Neo4j container.
param()

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
& $python -c 'import neo4j'
if ($LASTEXITCODE -ne 0) {
    throw 'Install the optional dependency: .\.venv\Scripts\python.exe -m pip install -r apps/api/requirements-graph.txt'
}

$passwordLine = @(Get-Content -LiteralPath '.env' | Where-Object {
    $_ -match '^PROCUREGRAPH_NEO4J_PASSWORD=.+$'
})
if ($passwordLine.Count -eq 0) {
    $bytes = New-Object byte[] 24
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $generated = [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
    Add-Content -LiteralPath '.env' -Value "`r`nPROCUREGRAPH_NEO4J_PASSWORD=$generated" -Encoding UTF8
    $passwordLine = @("PROCUREGRAPH_NEO4J_PASSWORD=$generated")
    Write-Output 'PASS: generated a local Neo4j password in ignored .env'
}
if ($passwordLine.Count -ne 1) { throw 'Expected one Neo4j password in .env' }
$env:PROCUREGRAPH_NEO4J_PASSWORD = $passwordLine[0].Substring('PROCUREGRAPH_NEO4J_PASSWORD='.Length)

if ((docker info --format '{{.OSType}}').Trim() -ne 'linux') {
    throw 'Start Docker Desktop with the Linux engine.'
}
& powershell -ExecutionPolicy Bypass -File '.\scripts\check_graph_manifest.ps1'
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL source manifest recheck failed' }
$running = @(docker ps --format '{{.Names}}')
if ($LASTEXITCODE -ne 0 -or $running -match '^procuregraph-(demo-postgres|vector-qdrant)-') {
    throw 'PostgreSQL or Qdrant is still running; stop it before starting Neo4j.'
}

$graphStarted = $false
try {
    docker compose -f docker-compose.graph.yml -p procuregraph-graph up -d neo4j
    if ($LASTEXITCODE -ne 0) { throw 'Neo4j could not start' }
    $graphStarted = $true
    $address = docker compose -f docker-compose.graph.yml -p procuregraph-graph port neo4j 7687
    if ($LASTEXITCODE -ne 0 -or $address -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw "Unexpected Neo4j Bolt address: $address"
    }
    $env:PROCUREGRAPH_NEO4J_BOLT = "bolt://127.0.0.1:$($Matches[1])"
    & $python -m datasets.generator.check_neo4j_price_graph
    if ($LASTEXITCODE -ne 0) { throw 'Neo4j graph import check failed' }
}
finally {
    if ($graphStarted) { docker compose -f docker-compose.graph.yml -p procuregraph-graph stop neo4j }
}
