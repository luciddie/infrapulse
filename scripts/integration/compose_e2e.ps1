$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..' '..')).Path
$composeFile = Join-Path $repoRoot 'compose.integration.yml'
$proj = "infrapulse-it-$PID-$(Get-Random -Maximum 99999)"
$imageOverride = $null
$composeFiles = @('-f', $composeFile)
if ($env:INFRAPULSE_IMAGE) {
    $imageOverride = Join-Path ([System.IO.Path]::GetTempPath()) "compose.image_override.$PID.yml"
    @"
services:
  migrate:
    image: $($env:INFRAPULSE_IMAGE)
  app:
    image: $($env:INFRAPULSE_IMAGE)
"@ | Set-Content -Path $imageOverride -Encoding UTF8
    $composeFiles += @('-f', $imageOverride)
}

function Invoke-Checked {
    param([scriptblock]$Command, [string]$ErrorMessage)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage (exit code $LASTEXITCODE)"
    }
}

Push-Location $repoRoot
try {
    $env:INTEGRATION_MONITORING_ENABLED = 'false'
    $env:INTEGRATION_MONITORING_INTERVAL = '5'

    Write-Output "--- 1. Start postgres ($proj) ---"
    Invoke-Checked { docker compose -p $proj @composeFiles up -d postgres --wait } "Postgres failed to start"

    Write-Output "--- 2. One-shot migrate (fresh + repeated) ---"
    Invoke-Checked { docker compose -p $proj @composeFiles run --rm migrate } "Initial migration failed"
    Invoke-Checked { docker compose -p $proj @composeFiles run --rm migrate } "Repeated migration failed"

    Write-Output "--- 3. Start app & prometheus (monitoring disabled) ---"
    Invoke-Checked { docker compose -p $proj @composeFiles up -d app prometheus } "Failed to start app and prometheus"
    Start-Sleep -Seconds 4

    Write-Output "--- 4. Verify /health, /ready, /api/scan, /metrics ---"
    $scanScript = @"
import json, time, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5) as r:
    assert r.status == 200
    print('/health:', r.read().decode())
with urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=5) as r:
    assert r.status == 200
    print('/ready:', r.read().decode())

req = urllib.request.Request(
    'http://127.0.0.1:8000/api/scan',
    data=json.dumps({'network': '127.0.0.1/32'}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
with urllib.request.urlopen(req, timeout=5) as r:
    assert r.status == 202
    scan_id = json.loads(r.read().decode())['scan_id']

for _ in range(25):
    with urllib.request.urlopen(f'http://127.0.0.1:8000/api/scans/{scan_id}', timeout=5) as r:
        st = json.loads(r.read().decode())
        if st['status'] == 'completed':
            break
    time.sleep(0.2)
else:
    raise AssertionError('Scan did not complete')

with urllib.request.urlopen('http://127.0.0.1:8000/metrics', timeout=5) as r:
    body = r.read().decode()
    assert 'infrapulse_monitoring_enabled 0.0' in body
print('SCAN_ID=' + scan_id)
"@
    $scanOutput = docker compose -p $proj @composeFiles exec -T app python -c $scanScript
    if ($LASTEXITCODE -ne 0) { throw "API/metrics verification failed" }
    $scanOutput | Write-Output
    $scanIdMatch = $scanOutput | Select-String -Pattern '^SCAN_ID=(.+)$'
    if (-not $scanIdMatch) { throw "Failed to capture SCAN_ID" }
    $scanId = $scanIdMatch.Matches[0].Groups[1].Value.Trim()

    Write-Output "--- 5. Verify Prometheus scraping app:8000 ---"
    Start-Sleep -Seconds 16
    $promScript = @"
import json, urllib.request
with urllib.request.urlopen('http://prometheus:9090/api/v1/targets', timeout=5) as r:
    data = json.loads(r.read().decode())
targets = [t for t in data['data']['activeTargets'] if t['labels'].get('job') == 'infrapulse']
assert targets and targets[0]['health'] == 'up' and targets[0]['labels'].get('instance') == 'app:8000', f'Unexpected targets: {targets}'
print('PROM_TARGET:', targets[0]['scrapeUrl'], targets[0]['health'], targets[0]['labels'])
"@
    Invoke-Checked { docker compose -p $proj @composeFiles exec -T app python -c $promScript } "Prometheus target verification failed"

    Write-Output "--- 6. Enable monitoring scheduler and verify cycle ---"
    $env:INTEGRATION_MONITORING_ENABLED = 'true'
    $env:INTEGRATION_MONITORING_INTERVAL = '2'
    Invoke-Checked { docker compose -p $proj @composeFiles up -d app } "Failed to enable monitoring scheduler"
    Start-Sleep -Seconds 6
    $schedScript = @"
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/metrics', timeout=5) as r:
    body = r.read().decode()
assert 'infrapulse_monitoring_enabled 1.0' in body
assert 'infrapulse_monitoring_cycles_total{status="success"}' in body
for line in body.splitlines():
    if line.startswith(('infrapulse_monitoring_enabled ', 'infrapulse_monitoring_last_success_timestamp_seconds ', 'infrapulse_monitoring_cycles_total')):
        print('SCHED_METRIC:', line)
"@
    Invoke-Checked { docker compose -p $proj @composeFiles exec -T app python -c $schedScript } "Scheduler metric verification failed"

    Write-Output "--- 7. Disable monitoring, restart app, verify DB persistence ---"
    $env:INTEGRATION_MONITORING_ENABLED = 'false'
    Invoke-Checked { docker compose -p $proj @composeFiles up -d app } "Failed to restart app"
    Start-Sleep -Seconds 4
    $persistScript = @"
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=5) as r:
    assert r.status == 200
    print('POST_RESTART /ready:', r.read().decode())
with urllib.request.urlopen('http://127.0.0.1:8000/api/scans/$scanId', timeout=5) as r:
    data = json.loads(r.read().decode())
    assert data['status'] == 'completed', f'Unexpected scan state: {data}'
    print('POST_RESTART /api/scans:', data['id'], data['status'])
"@
    Invoke-Checked { docker compose -p $proj @composeFiles exec -T app python -c $persistScript } "Persistence verification failed"
}
finally {
    Remove-Item Env:INTEGRATION_MONITORING_ENABLED -ErrorAction SilentlyContinue
    Remove-Item Env:INTEGRATION_MONITORING_INTERVAL -ErrorAction SilentlyContinue
    Write-Output "--- 8. Clean shutdown & volume removal ($proj) ---"
    docker compose -p $proj @composeFiles down -v --remove-orphans
    if ($imageOverride) { Remove-Item -Force $imageOverride -ErrorAction SilentlyContinue }
    $remC = (docker ps -a --filter "label=com.docker.compose.project=$proj" --format "{{.Names}}") -join ","
    $remV = (docker volume ls --filter "label=com.docker.compose.project=$proj" --format "{{.Name}}") -join ","
    $remN = (docker network ls --filter "label=com.docker.compose.project=$proj" --format "{{.Name}}") -join ","
    Write-Output "CLEANUP: containers=[$remC] volumes=[$remV] networks=[$remN]"
    Pop-Location
}
