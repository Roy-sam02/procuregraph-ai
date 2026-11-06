# Local synthetic check; both small containers run briefly, then stop.
param()

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path

$settings = @{}
Get-Content -LiteralPath '.env' | ForEach-Object {
    if ($_ -match '^([A-Za-z_][A-Za-z_0-9]*)=(.*)$') {
        $settings[$Matches[1]] = $Matches[2]
    }
}
foreach ($name in @('PROCUREGRAPH_DB_PASSWORD', 'PROCUREGRAPH_MINIO_USER', 'PROCUREGRAPH_MINIO_PASSWORD')) {
    if (-not $settings[$name]) { throw "Missing $name in .env" }
    [Environment]::SetEnvironmentVariable($name, $settings[$name], 'Process')
}
if ($settings['PROCUREGRAPH_MINIO_IMAGE']) {
    $env:PROCUREGRAPH_MINIO_IMAGE = $settings['PROCUREGRAPH_MINIO_IMAGE']
}
elseif (-not $env:PROCUREGRAPH_MINIO_IMAGE) {
    $saved = docker inspect procuregraph-storage-minio-1 --format '{{.Config.Image}}' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $saved) {
        throw 'Set PROCUREGRAPH_MINIO_IMAGE to the pinned image used for your saved MinIO volume.'
    }
    $env:PROCUREGRAPH_MINIO_IMAGE = $saved.Trim()
}

$pgStarted = $false
$minioStarted = $false
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
    $pgAddress = docker compose -p procuregraph-demo port postgres 5432
    if ($LASTEXITCODE -ne 0 -or $pgAddress -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw "Unexpected PostgreSQL address: $pgAddress"
    }
    $env:PROCUREGRAPH_DB_PORT = $Matches[1]

    docker compose -f docker-compose.storage.yml -p procuregraph-storage up -d minio
    if ($LASTEXITCODE -ne 0) { throw 'MinIO could not start' }
    $minioStarted = $true
    $minioAddress = docker compose -f docker-compose.storage.yml -p procuregraph-storage port minio 9000
    if ($LASTEXITCODE -ne 0 -or $minioAddress -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw "Unexpected MinIO address: $minioAddress"
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

    & $python -m apps.api.app.services.check_verified_api
    if ($LASTEXITCODE -ne 0) { throw 'Verified evidence API check failed' }

    & $python -m datasets.generator.export_evidence_locator '.local-fixtures\evidence_locator.json'
    if ($LASTEXITCODE -ne 0) { throw 'Stored source locator export failed' }
    & $python -m datasets.generator.build_contract_passages `
        '.local-fixtures\evidence_locator.json' '.local-fixtures\contract_passages_v1.json' `
        --endpoint $env:PROCUREGRAPH_MINIO_ENDPOINT
    if ($LASTEXITCODE -ne 0) { throw 'Verified passage build failed' }
}
finally {
    if ($minioStarted) {
        docker compose -f docker-compose.storage.yml -p procuregraph-storage stop minio
    }
    if ($pgStarted) {
        docker compose -p procuregraph-demo stop postgres
    }
}
