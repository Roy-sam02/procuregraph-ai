param()

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

$project = 'procuregraph-demo'
$python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
$envPath = Join-Path (Get-Location).Path '.env'
$pidPath = Join-Path (Get-Location).Path '.local-demo.pid'
$portPath = Join-Path (Get-Location).Path '.local-demo.port'
$outPath = Join-Path (Get-Location).Path '.local-demo.out.log'
$errPath = Join-Path (Get-Location).Path '.local-demo.err.log'

if (Test-Path -LiteralPath $pidPath) {
    $oldPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
        throw 'A recorded demo API process is running. Use scripts/stop_local_demo.ps1 first.'
    }
    Remove-Item -LiteralPath $pidPath
}

if (-not (Test-Path -LiteralPath $envPath)) {
    $password = [guid]::NewGuid().ToString('N')
    [System.IO.File]::WriteAllText(
        $envPath, "PROCUREGRAPH_DB_PASSWORD=$password`n"
    )
}

$passwordLine = @(Get-Content -LiteralPath $envPath | Where-Object {
    $_ -match '^PROCUREGRAPH_DB_PASSWORD=.+$'
})
if ($passwordLine.Count -ne 1) {
    throw 'The existing .env needs exactly one PROCUREGRAPH_DB_PASSWORD=value line.'
}
$env:PROCUREGRAPH_DB_PASSWORD = $passwordLine[0].Substring(
    'PROCUREGRAPH_DB_PASSWORD='.Length
)
$env:PROCUREGRAPH_ENABLE_DEMO_DB_API = '1'

$apiProcess = $null
$success = $false
try {
    docker compose -p $project up -d postgres
    if ($LASTEXITCODE -ne 0) { throw 'Could not start PostgreSQL.' }

    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        docker compose -p $project exec -T postgres `
            pg_isready -h 127.0.0.1 -U postgres -d procuregraph | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'PostgreSQL did not become ready.' }

    $endpoint = docker compose -p $project port postgres 5432
    if ($LASTEXITCODE -ne 0 -or $endpoint -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw 'Could not determine the PostgreSQL port.'
    }
    $env:PROCUREGRAPH_DB_PORT = $Matches[1]

    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Migration failed.' }

    $rowCount = docker compose -p $project exec -T postgres `
        psql -X -v ON_ERROR_STOP=1 -U postgres -d procuregraph -At `
        -c "SELECT count(*) FROM invoices WHERE invoice_number = 'INV-001'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not check existing demo data.' }
    $rowCount = $rowCount.Trim()
    if ($rowCount -eq '0') {
        & $python -m datasets.generator.seed_price_case `
            datasets/fixtures/price_case_001.json
        if ($LASTEXITCODE -ne 0) { throw 'Synthetic seed failed.' }
    }
    elseif ($rowCount -ne '1') {
        throw "Expected zero or one synthetic invoice, found $rowCount."
    }

    $tenantId = docker compose -p $project exec -T postgres `
        psql -X -v ON_ERROR_STOP=1 -U postgres -d procuregraph -At `
        -c "SELECT tenant_id FROM suppliers WHERE legal_name = 'Aster Supplies'"
    if ($LASTEXITCODE -ne 0 -or -not $tenantId) { throw 'Could not read demo tenant.' }
    $tenantId = $tenantId.Trim()

    $lineId = docker compose -p $project exec -T postgres `
        psql -X -v ON_ERROR_STOP=1 -U postgres -d procuregraph -At `
        -c "SELECT il.id FROM invoice_lines il JOIN invoices i ON i.id = il.invoice_id WHERE i.invoice_number = 'INV-001'"
    if ($LASTEXITCODE -ne 0 -or -not $lineId) { throw 'Could not read demo invoice line.' }
    $lineId = $lineId.Trim()

    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback, 0
    )
    $listener.Start()
    $apiPort = $listener.LocalEndpoint.Port
    $listener.Stop()

    $apiProcess = Start-Process -FilePath $python `
        -ArgumentList @(
            '-m', 'uvicorn', 'apps.api.app.main:app',
            '--host', '127.0.0.1', '--port', "$apiPort"
        ) -PassThru -RedirectStandardOutput $outPath -RedirectStandardError $errPath

    $baseUrl = "http://127.0.0.1:$apiPort"
    $apiReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "$baseUrl/health/live" `
                -Method Get -TimeoutSec 2
            if ($health.status -eq 'ok') { $apiReady = $true; break }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $apiReady) {
        Get-Content -LiteralPath $errPath -ErrorAction SilentlyContinue
        throw 'Uvicorn did not become ready.'
    }

    $body = @{
        tenant_id = $tenantId
        invoice_line_id = $lineId
    } | ConvertTo-Json -Compress
    $assessment = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/pricing/cases/assess" `
        -Method Post -ContentType 'application/json' -Body $body
    if ([decimal]$assessment.allowed_unit_price -ne [decimal]105 -or
        [decimal]$assessment.excess_amount -ne [decimal]10 -or
        $assessment.is_violation -ne $true) {
        throw "Unexpected assessment: $($assessment | ConvertTo-Json -Compress)"
    }

    [System.IO.File]::WriteAllText($pidPath, "$($apiProcess.Id)`n")
    [System.IO.File]::WriteAllText($portPath, "$apiPort`n")
    $success = $true
    Write-Output "PASS: demo API at $baseUrl/docs returned INR 105 limit and INR 10 excess."
}
finally {
    if (-not $success) {
        if ($apiProcess -and -not $apiProcess.HasExited) {
            Stop-Process -Id $apiProcess.Id -Force -ErrorAction SilentlyContinue
        }
        docker compose -p $project stop postgres | Out-Null
        Remove-Item -LiteralPath $pidPath, $portPath -ErrorAction SilentlyContinue
    }
}
