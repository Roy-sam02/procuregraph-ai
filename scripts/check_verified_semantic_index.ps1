# Sequential PostgreSQL and Qdrant stages for verified local semantic indexing.
param()

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
& $python -c 'import fastembed'
if ($LASTEXITCODE -ne 0) {
    throw 'Install the optional dependency: .\.venv\Scripts\python.exe -m pip install -r apps/api/requirements-retrieval.txt'
}
$env:OMP_NUM_THREADS = '2'
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
    & $python -m datasets.generator.export_vector_snapshot `
        '.local-fixtures\contract_passages_v1.json' '.local-fixtures\qdrant_snapshot_v1.json'
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL vector export failed' }
}
finally {
    if ($pgStarted) { docker compose -p procuregraph-demo stop postgres }
}

$qdrantStarted = $false
try {
    docker compose -f docker-compose.vector.yml -p procuregraph-vector up -d qdrant
    if ($LASTEXITCODE -ne 0) { throw 'Qdrant could not start' }
    $qdrantStarted = $true
    $address = docker compose -f docker-compose.vector.yml -p procuregraph-vector port qdrant 6333
    if ($LASTEXITCODE -ne 0 -or $address -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw "Unexpected Qdrant address: $address"
    }
    $endpoint = "http://127.0.0.1:$($Matches[1])"
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $health = Invoke-WebRequest -Uri "$endpoint/healthz" -UseBasicParsing -TimeoutSec 2
            if ($health.StatusCode -eq 200) { $ready = $true; break }
        }
        catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'Qdrant did not become ready' }
    & $python -m datasets.generator.check_verified_semantic_index `
        '.local-fixtures\qdrant_snapshot_v1.json' '.local-fixtures\verified_semantic_report_v1.json' `
        --endpoint $endpoint --cache-dir '.local-fixtures\fastembed_cache'
    if ($LASTEXITCODE -ne 0) { throw 'Verified semantic index check failed' }
}
finally {
    if ($qdrantStarted) { docker compose -f docker-compose.vector.yml -p procuregraph-vector stop qdrant }
}
