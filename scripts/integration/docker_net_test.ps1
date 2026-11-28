$ErrorActionPreference = 'Stop'

$runId = "$PID-$(Get-Random -Maximum 99999)"
$net = "infrapulse-net-$runId"
$target = "infrapulse-target-$runId"
$probe = "infrapulse-probe-$runId"
$image = if ($env:INFRAPULSE_IMAGE) { $env:INFRAPULSE_IMAGE } else { "infrapulse:dev" }

function Invoke-Checked {
    param([scriptblock]$Command, [string]$ErrorMessage)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage (exit code $LASTEXITCODE)"
    }
}

try {
    Invoke-Checked { docker network create --internal --subnet 172.31.250.0/24 $net | Out-Null } "Failed to create isolated network"
    Invoke-Checked {
        docker run -d --name $target --network $net `
            -e POSTGRES_PASSWORD=integration_test_only_password `
            -e MONITORING_ENABLED=false `
            -e TELEGRAM_ENABLED=false `
            -e DB_HOST=127.0.0.1 `
            $image | Out-Null
    } "Failed to start target container"
    Invoke-Checked {
        docker run -d --name $probe --network $net `
            -e POSTGRES_PASSWORD=integration_test_only_password `
            -e MONITORING_ENABLED=false `
            -e TELEGRAM_ENABLED=false `
            -e DB_HOST=127.0.0.1 `
            $image sleep 120 | Out-Null
    } "Failed to start probe container"

    Start-Sleep -Seconds 3

    $targetIp = (docker inspect -f "{{with index .NetworkSettings.Networks `"$net`"}}{{.IPAddress}}{{end}}" $target).Trim()
    $probeIp = (docker inspect -f "{{with index .NetworkSettings.Networks `"$net`"}}{{.IPAddress}}{{end}}" $probe).Trim()
    if (-not $targetIp -or -not $probeIp) {
        throw "Failed to resolve container IPs on $net"
    }
    Write-Output "TARGET_IP=$targetIp PROBE_IP=$probeIp"

    $pyScript = @"
from app.services.interfaces import get_interfaces, get_recommended_interfaces
from app.services.icmp import ping_host
from app.services.arp import get_arp_table
from app.services.tcp_checker import check_tcp
from app.services.http_checker import check_http

ifaces = get_interfaces()
rec = get_recommended_interfaces()
assert any(i['name'] == 'eth0' and i['ip'] == '$probeIp' and i['physical'] is False and i['recommended'] is True for i in ifaces), f'Unexpected ifaces: {ifaces}'
assert any(i['ip'] == '$probeIp' for i in rec), f'Missing recommended iface: {rec}'

ping_def = ping_host('$targetIp')
assert ping_def['status'] == 'online', f'Default ping failed: {ping_def}'

ping_bnd = ping_host('$targetIp', source_ip='$probeIp')
assert ping_bnd['status'] == 'online', f'Bound ping failed: {ping_bnd}'

arp = get_arp_table('$probeIp')
assert '$targetIp' in arp, f'Target missing from neighbour cache: {arp}'

tcp_res = check_tcp('$targetIp', 8000)
assert tcp_res['status'] == 'open', f'TCP check failed: {tcp_res}'

http_res = check_http('http://${targetIp}:8000/health')
assert http_res['status'] == 'healthy', f'HTTP check failed: {http_res}'

print('IFACES_OK:', len(ifaces))
print('PING_DEFAULT:', ping_def)
print('PING_BOUND:', ping_bnd)
print('ARP_TABLE:', arp)
print('TCP_CHECK:', tcp_res)
print('HTTP_CHECK:', http_res)
"@

    Invoke-Checked { docker exec $probe python -c $pyScript } "In-container network validation failed"

    $healthStatus = ''
    for ($i = 0; $i -lt 15; $i++) {
        $healthStatus = (docker inspect --format "{{.State.Health.Status}}" $target).Trim()
        if ($healthStatus -eq 'healthy') { break }
        Start-Sleep -Seconds 3
    }
    Write-Output "TARGET_HEALTHCHECK=$healthStatus"
    if ($healthStatus -ne 'healthy') {
        throw "Target container did not become healthy (status=$healthStatus)"
    }
}
finally {
    foreach ($c in @($probe, $target)) {
        $exists = docker ps -a --filter "name=^/$c$" --format "{{.Names}}"
        if ($exists -eq $c) {
            docker rm -f $c | Out-Null
        }
    }
    $netExists = docker network ls --filter "name=^$net$" --format "{{.Name}}"
    if ($netExists -eq $net) {
        docker network rm $net | Out-Null
    }
    $remC = (docker ps -a --filter "name=$runId" --format "{{.Names}}") -join ","
    $remN = (docker network ls --filter "name=$runId" --format "{{.Name}}") -join ","
    Write-Output "CLEANUP_CONTAINERS=[$remC] CLEANUP_NETWORKS=[$remN]"
}
