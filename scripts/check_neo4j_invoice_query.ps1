# Query only the retained Neo4j graph; PostgreSQL and Qdrant stay stopped.
param()

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
& $python -c 'import neo4j'
if ($LASTEXITCODE -ne 0) { throw 'Install apps/api/requirements-graph.txt' }
$passwordLine = @(Get-Content -LiteralPath '.env' | Where-Object {
    $_ -match '^PROCUREGRAPH_NEO4J_PASSWORD=.+$'
})
if ($passwordLine.Count -ne 1) { throw 'Expected one saved Neo4j password in .env' }
$env:PROCUREGRAPH_NEO4J_PASSWORD = $passwordLine[0].Substring('PROCUREGRAPH_NEO4J_PASSWORD='.Length)
if ((docker info --format '{{.OSType}}').Trim() -ne 'linux') {
    throw 'Start Docker Desktop with the Linux engine.'
}
$running = @(docker ps --format '{{.Names}}')
if ($LASTEXITCODE -ne 0 -or $running -match '^procuregraph-(demo-postgres|vector-qdrant)-') {
    throw 'PostgreSQL or Qdrant is running; stop it for the low-memory graph check.'
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
    & $python -m datasets.generator.check_neo4j_invoice_query
    if ($LASTEXITCODE -ne 0) { throw 'Read-only invoice graph check failed' }
}
finally {
    if ($graphStarted) { docker compose -f docker-compose.graph.yml -p procuregraph-graph stop neo4j }
}
