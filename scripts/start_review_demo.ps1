# Loopback-only local review view: PostgreSQL + FastAPI + Vite. No other demo services.
param()

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
if (-not (Get-Command node -ErrorAction SilentlyContinue) -or
    -not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js before running the React demo.'
}
if (-not (Test-Path -LiteralPath 'apps\web\node_modules\vite')) {
    throw 'Run npm ci --prefix apps/web first.'
}
$passwordLine = @(Get-Content -LiteralPath '.env' | Where-Object {
    $_ -match '^PROCUREGRAPH_DB_PASSWORD=.+$'
})
if ($passwordLine.Count -ne 1) { throw 'Expected one saved PostgreSQL password in .env' }
$env:PROCUREGRAPH_DB_PASSWORD = $passwordLine[0].Substring('PROCUREGRAPH_DB_PASSWORD='.Length)
if ((docker info --format '{{.OSType}}').Trim() -ne 'linux') {
    throw 'Start Docker Desktop with the Linux engine.'
}
$running = @(docker ps --format '{{.Names}}')
if ($LASTEXITCODE -ne 0 -or $running -match '^procuregraph-(demo-postgres|storage-minio|graph-neo4j|vector-qdrant)-') {
    throw 'A demo container is already running; stop it before this low-memory review demo.'
}
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8000 is already in use.'
}
$pgStarted = $false
$api = $null
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
    $env:PROCUREGRAPH_ENABLE_DEMO_DB_API = '1'
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $env:PROCUREGRAPH_DEMO_EVIDENCE_TOKEN = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')

    $reviewerBytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($reviewerBytes) } finally { $rng.Dispose() }
    $reviewerToken = [Convert]::ToBase64String($reviewerBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($reviewerToken))).Replace('-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
    $env:PROCUREGRAPH_DEMO_REVIEWER = @{
        reviewer_id = [Guid]::NewGuid().ToString()
        tenant_id = '6c4b7c99-14f3-5c71-8b65-ed50dc9ce43c'
        token_sha256 = $digest
    } | ConvertTo-Json -Compress

    $api = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'apps.api.app.main:app',
        '--host', '127.0.0.1', '--port', '8000') -PassThru -NoNewWindow
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($api.HasExited) { throw 'FastAPI process stopped before becoming ready' }
        try {
            $health = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health/live' `
                -UseBasicParsing -TimeoutSec 2
            if ($health.StatusCode -eq 200) { $ready = $true; break }
        }
        catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'FastAPI did not become ready' }

    Write-Host 'Open http://127.0.0.1:5173 in your browser.'
    Write-Host "Local demo token (paste into the page, do not share): $env:PROCUREGRAPH_DEMO_EVIDENCE_TOKEN"
    Write-Host "Local reviewer token (for the decision API only, do not share): $reviewerToken"
    Write-Host 'Press Ctrl+C here when finished to stop the API and PostgreSQL.'
    & npm.cmd run dev --prefix apps/web
}
finally {
    if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force }
    if ($pgStarted) { docker compose -p procuregraph-demo stop postgres }
}
