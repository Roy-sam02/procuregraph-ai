# Read PostgreSQL, MinIO, then Neo4j sequentially; keep all named volumes.
param()

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
& $python -c 'import langgraph, neo4j'
if ($LASTEXITCODE -ne 0) { throw 'Install apps/api/requirements-agent.txt and requirements-graph.txt' }

$settings = @{}
Get-Content -LiteralPath '.env' | ForEach-Object {
    if ($_ -match '^([A-Za-z_][A-Za-z_0-9]*)=(.*)$') {
        $settings[$Matches[1]] = $Matches[2]
    }
}
foreach ($name in @('PROCUREGRAPH_DB_PASSWORD', 'PROCUREGRAPH_MINIO_USER',
                    'PROCUREGRAPH_MINIO_PASSWORD', 'PROCUREGRAPH_NEO4J_PASSWORD')) {
    if (-not $settings[$name]) { throw "Missing $name in .env" }
    [Environment]::SetEnvironmentVariable($name, $settings[$name], 'Process')
}
if ($settings['PROCUREGRAPH_MINIO_IMAGE']) {
    $env:PROCUREGRAPH_MINIO_IMAGE = $settings['PROCUREGRAPH_MINIO_IMAGE']
}
elseif (-not $env:PROCUREGRAPH_MINIO_IMAGE) {
    $saved = docker inspect procuregraph-storage-minio-1 --format '{{.Config.Image}}' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $saved) {
        throw 'Set PROCUREGRAPH_MINIO_IMAGE to the image used for the saved MinIO volume.'
    }
    $env:PROCUREGRAPH_MINIO_IMAGE = $saved.Trim()
}
if ((docker info --format '{{.OSType}}').Trim() -ne 'linux') {
    throw 'Start Docker Desktop with the Linux engine.'
}
$running = @(docker ps --format '{{.Names}}')
if ($LASTEXITCODE -ne 0 -or $running -match '^procuregraph-(demo-postgres|storage-minio|graph-neo4j|vector-qdrant)-') {
    throw 'A demo container is already running; stop it before the sequential low-memory check.'
}

$tempDir = Join-Path '.local-fixtures' ([Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
$priceFile = Join-Path $tempDir 'price.json'
$pdfFile = Join-Path $tempDir 'pdf.json'
$resultFile = Join-Path $tempDir 'result.json'
$pgStarted = $false
$minioStarted = $false
$graphStarted = $false
try {
    $pgStarted = $true
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
    & $python -m datasets.generator.check_live_investigation price $priceFile
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL investigation source check failed' }
    docker compose -p procuregraph-demo stop postgres
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL could not stop' }
    $pgStarted = $false

    $minioStarted = $true
    docker compose -f docker-compose.storage.yml -p procuregraph-storage up -d minio
    if ($LASTEXITCODE -ne 0) { throw 'MinIO could not start' }
    $address = docker compose -f docker-compose.storage.yml -p procuregraph-storage port minio 9000
    if ($LASTEXITCODE -ne 0 -or $address -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw "Unexpected MinIO address: $address"
    }
    $env:PROCUREGRAPH_MINIO_ENDPOINT = "http://127.0.0.1:$($Matches[1])"
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $health = Invoke-WebRequest -Uri "$env:PROCUREGRAPH_MINIO_ENDPOINT/minio/health/ready" `
                -UseBasicParsing -TimeoutSec 2
            if ($health.StatusCode -eq 200) { $ready = $true; break }
        }
        catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'MinIO did not become ready' }
    & $python -m datasets.generator.check_live_investigation pdf $priceFile $pdfFile
    if ($LASTEXITCODE -ne 0) { throw 'PDF investigation source check failed' }
    docker compose -f docker-compose.storage.yml -p procuregraph-storage stop minio
    if ($LASTEXITCODE -ne 0) { throw 'MinIO could not stop' }
    $minioStarted = $false

    $graphStarted = $true
    docker compose -f docker-compose.graph.yml -p procuregraph-graph up -d neo4j
    if ($LASTEXITCODE -ne 0) { throw 'Neo4j could not start' }
    $address = docker compose -f docker-compose.graph.yml -p procuregraph-graph port neo4j 7687
    if ($LASTEXITCODE -ne 0 -or $address -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw "Unexpected Neo4j Bolt address: $address"
    }
    $env:PROCUREGRAPH_NEO4J_BOLT = "bolt://127.0.0.1:$($Matches[1])"
    & $python -m datasets.generator.check_neo4j_invoice_query
    if ($LASTEXITCODE -ne 0) { throw 'Neo4j did not become ready or source chain differs' }
    & $python -m datasets.generator.check_live_investigation finish $priceFile $pdfFile $resultFile
    if ($LASTEXITCODE -ne 0) { throw 'Staged live investigation failed' }
    docker compose -f docker-compose.graph.yml -p procuregraph-graph stop neo4j
    if ($LASTEXITCODE -ne 0) { throw 'Neo4j could not stop' }
    $graphStarted = $false

    $pgStarted = $true
    docker compose -p procuregraph-demo up -d postgres
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL could not restart' }
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        docker compose -p procuregraph-demo exec -T postgres `
            pg_isready -h 127.0.0.1 -U postgres -d procuregraph | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'PostgreSQL did not become ready after restart' }
    $address = docker compose -p procuregraph-demo port postgres 5432
    if ($LASTEXITCODE -ne 0 -or $address -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw "Unexpected PostgreSQL address: $address"
    }
    $env:PROCUREGRAPH_DB_PORT = $Matches[1]
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Investigation migration failed' }
    & $python -m datasets.generator.check_live_investigation persist $priceFile $pdfFile $resultFile
    if ($LASTEXITCODE -ne 0) { throw 'Verified finding persistence failed' }
}
finally {
    if ($graphStarted) { docker compose -f docker-compose.graph.yml -p procuregraph-graph stop neo4j }
    if ($minioStarted) { docker compose -f docker-compose.storage.yml -p procuregraph-storage stop minio }
    if ($pgStarted) { docker compose -p procuregraph-demo stop postgres }
    Remove-Item -LiteralPath $tempDir -Recurse -Force
}
