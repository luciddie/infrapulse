$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$composeFile = Join-Path $repoRoot 'compose.integration.yml'
$proj = "infrapulse-rel-$PID-$(Get-Random -Maximum 99999)"
$failOverride = Join-Path ([System.IO.Path]::GetTempPath()) "compose.fail_migrate.$PID.yml"

function Invoke-Checked {
    param([scriptblock]$Command, [string]$ErrorMessage)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage (exit code $LASTEXITCODE)"
    }
}

@"
services:
  migrate:
    command: ["alembic", "upgrade", "nonexistent_revision"]
"@ | Set-Content -Path $failOverride -Encoding UTF8

Push-Location $repoRoot
try {
    $env:INTEGRATION_MONITORING_ENABLED = 'false'
    $env:INTEGRATION_MONITORING_INTERVAL = '5'

    Write-Output "--- 1. Controlled migration failure & app blocked ($proj) ---"
    Invoke-Checked { docker compose -p $proj -f $composeFile up -d postgres --wait } "Postgres failed to start"

    $ErrorActionPreference = 'Continue'
    docker compose -p $proj -f $composeFile -f $failOverride up -d app 2>&1 | Out-String | Write-Output
    $failRc = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($failRc -eq 0) {
        throw "Expected migration failure to return non-zero exit code"
    }
    $appState = (docker ps -a --filter "label=com.docker.compose.project=$proj" --filter "label=com.docker.compose.service=app" --format "{{.State}}").Trim()
    if ($appState -eq 'running') {
        throw "App started despite migration failure!"
    }
    Write-Output "MIGRATE_FAIL_RC=$failRc APP_STATE=[$appState]"

    Write-Output "--- 2. Successful migration recovery & app startup ---"
    Invoke-Checked { docker compose -p $proj -f $composeFile up -d app } "Recovery startup failed"
    Start-Sleep -Seconds 4
    Invoke-Checked { docker compose -p $proj -f $composeFile exec -T app python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=5); assert r.status==200; print('RECOVERED /ready:', r.read().decode())" } "App not ready after recovery"

    Write-Output "--- 3. PostgreSQL shutdown -> /ready 503 & /health 200 ---"
    Invoke-Checked { docker compose -p $proj -f $composeFile stop postgres } "Failed to stop postgres"
    $failoverScript = @"
import urllib.request, urllib.error
with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5) as r:
    assert r.status == 200
    print('DB_DOWN /health:', r.status, r.read().decode())
try:
    urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=5)
    raise AssertionError('Expected /ready to return 503 when DB is down')
except urllib.error.HTTPError as e:
    assert e.code == 503
    print('DB_DOWN /ready:', e.code, e.read().decode())
"@
    Invoke-Checked { docker compose -p $proj -f $composeFile exec -T app python -c $failoverScript } "Failover readiness check failed"

    Write-Output "--- 4. PostgreSQL restart -> /ready 200 ---"
    Invoke-Checked { docker compose -p $proj -f $composeFile start postgres } "Failed to restart postgres"
    for ($i = 0; $i -lt 15; $i++) {
        $pgHealth = (docker compose -p $proj -f $composeFile ps postgres --format "{{.Health}}").Trim()
        if ($pgHealth -eq 'healthy') { break }
        Start-Sleep -Seconds 2
    }
    if ($pgHealth -ne 'healthy') { throw "Postgres did not recover to healthy" }
    Invoke-Checked { docker compose -p $proj -f $composeFile exec -T app python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=5); assert r.status==200; print('DB_UP /ready:', r.read().decode())" } "App did not recover readiness"

    Write-Output "--- 5. TCP & HTTP service monitoring + check persistence ---"
    Invoke-Checked { docker compose -p $proj -f $composeFile exec -T postgres psql -U infrapulse -d infrapulse -c "INSERT INTO devices (ip_address, status) VALUES ('127.0.0.1', 'online') RETURNING id;" } "Failed to seed test device"
    $svcScript = @"
import json, urllib.request
def post(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'Content-Type': 'application/json'} if payload is not None else {}
    req = urllib.request.Request('http://127.0.0.1:8000' + path, data=data, headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())

st1, tcp_svc = post('/api/services', {'device_id': 1, 'name': 'app-tcp', 'protocol': 'tcp', 'port': 8000})
st2, http_svc = post('/api/services', {'device_id': 1, 'name': 'app-http', 'protocol': 'http', 'url': 'http://127.0.0.1:8000/health', 'expected_status': 200})
assert st1 == 201 and st2 == 201
_, tcp_chk = post(f"/api/services/{tcp_svc['id']}/check")
_, http_chk = post(f"/api/services/{http_svc['id']}/check")
assert tcp_chk['status'] == 'open', f'Unexpected TCP check: {tcp_chk}'
assert http_chk['status'] == 'healthy', f'Unexpected HTTP check: {http_chk}'
print('TCP_CHECK:', tcp_chk['status'], 'HTTP_CHECK:', http_chk['status'])
for sid in (tcp_svc['id'], http_svc['id']):
    with urllib.request.urlopen(f'http://127.0.0.1:8000/api/services/{sid}/checks', timeout=5) as r:
        checks = json.loads(r.read().decode())['checks']
        assert r.status == 200 and len(checks) == 1
        print(f'PERSISTED_CHECKS_{sid}:', r.status, len(checks))
"@
    Invoke-Checked { docker compose -p $proj -f $composeFile exec -T app python -c $svcScript } "Service monitoring/persistence verification failed"

    Write-Output "--- 6. Resource stats & graceful shutdown with scheduler enabled ---"
    $env:INTEGRATION_MONITORING_ENABLED = 'true'
    $env:INTEGRATION_MONITORING_INTERVAL = '2'
    Invoke-Checked { docker compose -p $proj -f $composeFile up -d app } "Failed to start app with scheduler enabled"
    Start-Sleep -Seconds 5
    $appCid = (docker compose -p $proj -f $composeFile ps -q app).Trim()
    docker stats --no-stream --format "STATS: {{.Name}} CPU={{.CPUPerc}} MEM={{.MemUsage}}" $appCid
    Invoke-Checked { docker compose -p $proj -f $composeFile stop app } "Failed to stop app gracefully"
    $logs = docker compose -p $proj -f $composeFile logs --tail=20 app | Out-String
    $logs | Write-Output
    if ($logs -notmatch 'Application shutdown complete') {
        throw "Graceful shutdown log message missing"
    }
}
finally {
    Remove-Item Env:INTEGRATION_MONITORING_ENABLED -ErrorAction SilentlyContinue
    Remove-Item Env:INTEGRATION_MONITORING_INTERVAL -ErrorAction SilentlyContinue
    Remove-Item -Force $failOverride -ErrorAction SilentlyContinue
    Write-Output "--- 7. Cleanup ($proj) ---"
    docker compose -p $proj -f $composeFile down -v --remove-orphans
    $remC = (docker ps -a --filter "label=com.docker.compose.project=$proj" --format "{{.Names}}") -join ","
    $remV = (docker volume ls --filter "label=com.docker.compose.project=$proj" --format "{{.Name}}") -join ","
    $remN = (docker network ls --filter "label=com.docker.compose.project=$proj" --format "{{.Name}}") -join ","
    Write-Output "REL_CLEANUP: containers=[$remC] volumes=[$remV] networks=[$remN]"
    Pop-Location
}
