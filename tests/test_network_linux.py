import json
import subprocess
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import arp, icmp, interfaces, scanner


client = TestClient(app)


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["ip"],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


def test_linux_interfaces_parsing_multi_ip_gateway_metric_and_veth(monkeypatch):
    monkeypatch.setattr(interfaces.platform, "system", lambda: "Linux")

    addr_json = json.dumps([
        {
            "ifindex": 1,
            "ifname": "lo",
            "flags": ["LOOPBACK", "UP", "LOWER_UP"],
            "operstate": "UNKNOWN",
            "link_type": "loopback",
            "address": "00:00:00:00:00:00",
            "addr_info": [
                {"family": "inet", "local": "127.0.0.1", "prefixlen": 8},
                {"family": "inet6", "local": "::1", "prefixlen": 128},
            ],
        },
        {
            "ifindex": 2,
            "ifname": "eth0",
            "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
            "operstate": "UP",
            "link_type": "ether",
            "address": "02:42:ac:1e:00:02",
            "addr_info": [
                {"family": "inet", "local": "172.30.0.2", "prefixlen": 24},
                {"family": "inet", "local": "172.30.0.10", "prefixlen": 24},
                {"family": "inet", "local": "169.254.1.5", "prefixlen": 16},
            ],
        },
        {
            "ifindex": 3,
            "ifname": "eth1",
            "flags": ["BROADCAST", "MULTICAST"],
            "operstate": "DOWN",
            "link_type": "ether",
            "address": "02:42:ac:1f:00:02",
            "addr_info": [
                {"family": "inet", "local": "10.99.0.2", "prefixlen": 24},
            ],
        },
    ])

    link_json = json.dumps([
        {
            "ifindex": 1,
            "ifname": "lo",
            "flags": ["LOOPBACK", "UP", "LOWER_UP"],
            "operstate": "UNKNOWN",
            "link_type": "loopback",
        },
        {
            "ifindex": 2,
            "ifname": "eth0",
            "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
            "operstate": "UP",
            "link_type": "ether",
            "linkinfo": {"info_kind": "veth"},
        },
        {
            "ifindex": 3,
            "ifname": "eth1",
            "flags": ["BROADCAST", "MULTICAST"],
            "operstate": "DOWN",
            "link_type": "ether",
        },
    ])

    route_json = json.dumps([
        {"dst": "default", "gateway": "172.30.0.254", "dev": "eth0", "metric": 200},
        {"dst": "default", "gateway": "172.30.0.1", "dev": "eth0", "metric": 100},
        {"dst": "172.30.0.0/24", "dev": "eth0"},
    ])

    def fake_run(cmd, **kwargs):
        if cmd == ["ip", "-j", "address", "show"]:
            return _completed(addr_json)
        if cmd == ["ip", "-j", "link", "show"]:
            return _completed(link_json)
        if cmd == ["ip", "-j", "route", "show"]:
            return _completed(route_json)
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(interfaces.subprocess, "run", fake_run)

    result = interfaces.get_interfaces()
    assert len(result) == 5

    lo = result[0]
    assert lo["name"] == "lo"
    assert lo["status"] == "Up"
    assert lo["physical"] is False
    assert lo["recommended"] is False
    assert lo["gateway"] is None
    assert lo["mac"] is None

    eth0_primary, eth0_secondary, eth0_link_local = result[1], result[2], result[3]
    assert eth0_primary["ip"] == "172.30.0.2"
    assert eth0_secondary["ip"] == "172.30.0.10"
    assert eth0_primary["gateway"] == "172.30.0.1"
    assert eth0_primary["mac"] == "02:42:AC:1E:00:02"
    assert eth0_primary["physical"] is False
    assert eth0_primary["description"] == "veth"
    assert eth0_primary["network"] == "172.30.0.0/24"
    assert eth0_primary["netmask"] == "255.255.255.0"
    assert eth0_primary["recommended"] is True
    assert eth0_secondary["recommended"] is True
    assert eth0_link_local["recommended"] is False

    eth1 = result[4]
    assert eth1["status"] == "Down"
    assert eth1["gateway"] is None
    assert eth1["recommended"] is False


def test_linux_interfaces_malformed_and_error_cases(monkeypatch):
    monkeypatch.setattr(interfaces.platform, "system", lambda: "Linux")

    # Missing iproute2
    def raise_not_found(*args, **kwargs):
        raise FileNotFoundError("ip not found")

    monkeypatch.setattr(interfaces.subprocess, "run", raise_not_found)
    with pytest.raises(RuntimeError, match="iproute2"):
        interfaces.get_interfaces()

    # Subprocess timeout
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ip", timeout=10)

    monkeypatch.setattr(interfaces.subprocess, "run", raise_timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        interfaces.get_interfaces()

    # Invalid JSON
    monkeypatch.setattr(
        interfaces.subprocess,
        "run",
        lambda *a, **kw: _completed("{not-json"),
    )
    with pytest.raises(RuntimeError, match="Invalid JSON"):
        interfaces.get_interfaces()

    # Unexpected JSON structure (object instead of list)
    monkeypatch.setattr(
        interfaces.subprocess,
        "run",
        lambda *a, **kw: _completed('{"unexpected": true}'),
    )
    with pytest.raises(RuntimeError, match="Unexpected JSON"):
        interfaces.get_interfaces()

    # Malformed entries inside valid list are skipped safely
    addr_json = json.dumps([
        "bad-entry",
        {
            "ifindex": 2,
            "ifname": "eth0",
            "operstate": "UP",
            "link_type": "ether",
            "addr_info": [
                {"family": "inet", "local": "not-an-ip", "prefixlen": 24},
                {"family": "inet", "local": "172.30.0.2", "prefixlen": "24"},
            ],
        },
    ])
    monkeypatch.setattr(
        interfaces.subprocess,
        "run",
        lambda cmd, **kw: _completed(addr_json if "address" in cmd else "[]"),
    )
    assert interfaces.get_interfaces() == []


def test_linux_neighbour_parsing_and_filtering(monkeypatch):
    monkeypatch.setattr(arp.platform, "system", lambda: "Linux")

    neigh_json = json.dumps([
        # Valid list state + locally administered unicast MAC (preserved)
        {"dst": "172.30.0.3", "dev": "eth0", "lladdr": "02:42:ac:1e:00:03", "state": ["REACHABLE"]},
        # Valid string state
        {"dst": "172.30.0.4", "dev": "eth0", "lladdr": "aa-bb-cc-dd-ee-04", "state": "STALE"},
        # Unusable states
        {"dst": "172.30.0.5", "dev": "eth0", "lladdr": "02:42:ac:1e:00:05", "state": ["FAILED"]},
        {"dst": "172.30.0.6", "dev": "eth0", "state": ["INCOMPLETE"]},
        # Invalid / zero / broadcast / multicast MACs
        {"dst": "172.30.0.7", "dev": "eth0", "lladdr": "invalid-mac", "state": ["REACHABLE"]},
        {"dst": "172.30.0.8", "dev": "eth0", "lladdr": "00:00:00:00:00:00", "state": ["REACHABLE"]},
        {"dst": "172.30.0.9", "dev": "eth0", "lladdr": "ff:ff:ff:ff:ff:ff", "state": ["REACHABLE"]},
        {"dst": "172.30.0.10", "dev": "eth0", "lladdr": "01:00:5e:00:00:01", "state": ["REACHABLE"]},
        # Conflicting MACs for same IP
        {"dst": "172.30.0.11", "dev": "eth0", "lladdr": "02:42:ac:1e:00:11", "state": ["REACHABLE"]},
        {"dst": "172.30.0.11", "dev": "eth0", "lladdr": "02:42:ac:1e:00:12", "state": ["STALE"]},
        # IPv6 ignored
        {"dst": "fe80::1", "dev": "eth0", "lladdr": "02:42:ac:1e:00:99", "state": ["REACHABLE"]},
    ])

    recorded_cmds = []

    def fake_run(cmd, **kwargs):
        recorded_cmds.append(cmd)
        return _completed(neigh_json)

    monkeypatch.setattr(arp.subprocess, "run", fake_run)

    table = arp.get_arp_table()
    assert recorded_cmds[-1] == ["ip", "-j", "neigh", "show"]
    assert table == {
        "172.30.0.3": "02:42:AC:1E:00:03",
        "172.30.0.4": "AA:BB:CC:DD:EE:04",
    }

    # Interface-specific filtering
    monkeypatch.setattr(
        arp,
        "get_interfaces",
        lambda: [{"name": "eth0", "ip": "172.30.0.2"}],
    )
    filtered = arp.get_arp_table("172.30.0.2")
    assert recorded_cmds[-1] == ["ip", "-j", "neigh", "show", "dev", "eth0"]
    assert "172.30.0.3" in filtered

    # Non-matching interface_ip returns empty safely
    assert arp.get_arp_table("192.0.2.99") == {}

    # Missing iproute2 / timeout / invalid JSON return {} safely
    monkeypatch.setattr(arp.subprocess, "run", MagicMock(side_effect=FileNotFoundError()))
    assert arp.get_arp_table() == {}

    monkeypatch.setattr(
        arp.subprocess,
        "run",
        MagicMock(side_effect=subprocess.TimeoutExpired(cmd="ip", timeout=5)),
    )
    assert arp.get_arp_table() == {}

    monkeypatch.setattr(arp.subprocess, "run", lambda *a, **kw: _completed("bad-json"))
    assert arp.get_arp_table() == {}


def test_icmp_source_binding_and_scanner_propagation(monkeypatch):
    monkeypatch.setattr(icmp.platform, "system", lambda: "Linux")

    captured = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=b"64 bytes from 172.30.0.3: icmp_seq=1 ttl=64 time=0.25 ms\n",
            stderr=b"",
        )

    monkeypatch.setattr(icmp.subprocess, "run", fake_run)

    res_default = icmp.ping_host("172.30.0.3")
    assert res_default["status"] == "online"
    assert captured[-1] == ["ping", "-c", "1", "-W", "1", "172.30.0.3"]

    res_bound = icmp.ping_host("172.30.0.3", source_ip="172.30.0.2")
    assert res_bound["status"] == "online"
    assert captured[-1] == ["ping", "-c", "1", "-W", "1", "-I", "172.30.0.2", "172.30.0.3"]

    with pytest.raises(ValueError):
        icmp.ping_host("172.30.0.3", source_ip="not-an-ip")

    # Scanner passes explicit source_ip to ping_host when interface_ip is requested
    monkeypatch.setattr(
        scanner,
        "get_interfaces",
        lambda: [{
            "name": "eth0",
            "index": 2,
            "ip": "172.30.0.2",
            "prefix": 24,
            "gateway": "172.30.0.1",
            "mac": "02:42:AC:1E:00:02",
            "status": "Up",
            "physical": False,
            "description": "veth",
            "network": "172.30.0.0/24",
            "netmask": "255.255.255.0",
            "recommended": True,
        }],
    )
    monkeypatch.setattr(scanner, "get_arp_table", lambda iface_ip=None, interface_name=None: {})

    ping_calls = []

    def fake_ping(ip, source_ip=None):
        ping_calls.append((ip, source_ip))
        return {
            "ip": ip,
            "status": "online",
            "latency_ms": 0.5,
            "latency_upper_bound_ms": None,
        }

    monkeypatch.setattr(scanner, "ping_host", fake_ping)
    scan_res = scanner.scan_network("172.30.0.0/30", interface_ip="172.30.0.2")
    assert len(scan_res) == 2
    assert all(src == "172.30.0.2" for _, src in ping_calls)

    with pytest.raises(ValueError, match="No suitable network interface"):
        scanner.select_interface("172.30.0.0/24", interface_ip="10.0.0.1")


def test_windows_compatibility(monkeypatch):
    # Windows PowerShell interface parsing preserved
    monkeypatch.setattr(interfaces.platform, "system", lambda: "Windows")
    ps_output = json.dumps([
        {
            "name": "Ethernet",
            "index": 5,
            "ip": "192.168.1.10",
            "prefix": 24,
            "gateway": "192.168.1.1",
            "mac": "AA-BB-CC-DD-EE-FF",
            "status": "Up",
            "physical": True,
            "description": "Intel NIC",
        }
    ])
    monkeypatch.setattr(
        interfaces.subprocess,
        "run",
        lambda *a, **kw: _completed(ps_output),
    )
    win_ifaces = interfaces.get_interfaces()
    assert len(win_ifaces) == 1
    assert win_ifaces[0]["mac"] == "AA:BB:CC:DD:EE:FF"
    assert win_ifaces[0]["recommended"] is True

    # Windows ARP parsing preserved
    monkeypatch.setattr(arp.platform, "system", lambda: "Windows")
    arp_stdout = (
        "Interface: 192.168.1.10 --- 0x5\n"
        "  Internet Address      Physical Address      Type\n"
        "  192.168.1.1           00-11-22-33-44-55     dynamic\n"
    ).encode()
    monkeypatch.setattr(
        arp.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            args=["arp"], returncode=0, stdout=arp_stdout, stderr=b""
        ),
    )
    assert arp.get_arp_table("192.168.1.10") == {
        "192.168.1.1": "00:11:22:33:44:55"
    }


def test_network_api_error_responses(monkeypatch):
    from app.api import network as network_api
    from app.services.scan_manager import ScanConflictError

    monkeypatch.setattr(
        network_api,
        "get_interfaces",
        lambda: [{"name": "eth0", "ip": "172.30.0.2"}],
    )
    resp_200 = client.get("/api/interfaces")
    assert resp_200.status_code == 200
    assert resp_200.json()[0]["name"] == "eth0"

    monkeypatch.setattr(
        network_api,
        "get_interfaces",
        MagicMock(side_effect=NotImplementedError("unsupported")),
    )
    resp_501 = client.get("/api/interfaces")
    assert resp_501.status_code == 501

    monkeypatch.setattr(
        network_api,
        "get_interfaces",
        MagicMock(side_effect=RuntimeError("missing iproute2")),
    )
    resp_503 = client.get("/api/interfaces")
    assert resp_503.status_code == 503

    monkeypatch.setattr(
        network_api,
        "select_interface",
        MagicMock(side_effect=ValueError("No suitable network interface found")),
    )
    resp_400 = client.post(
        "/api/scan",
        json={"network": "172.30.0.0/24", "interface_ip": "10.0.0.1"},
    )
    assert resp_400.status_code == 400

    monkeypatch.setattr(
        network_api,
        "select_interface",
        lambda net, ip=None: {"name": "eth0", "ip": ip},
    )
    monkeypatch.setattr(
        network_api.scan_manager,
        "start_scan",
        MagicMock(side_effect=ScanConflictError("Another scan is already running")),
    )
    resp_409 = client.post(
        "/api/scan",
        json={"network": "172.30.0.0/24", "interface_ip": "172.30.0.2"},
    )
    assert resp_409.status_code == 409


def test_sysfs_physical_classification_and_multiple_interfaces(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(
        Path,
        "exists",
        lambda self: str(self).replace("\\", "/") in (
            "/sys/class/net",
            "/sys/class/net/eth0",
            "/sys/class/net/enp0s3",
            "/sys/class/net/enp0s3/device",
        ),
    )
    assert interfaces._is_linux_physical_interface("eth0", "ether", ["UP"], None) is False
    assert interfaces._is_linux_physical_interface("enp0s3", "ether", ["UP"], None) is True

    monkeypatch.setattr(
        scanner,
        "get_interfaces",
        lambda: [
            {
                "name": "eth0",
                "ip": "172.30.0.2",
                "status": "Up",
                "network": "172.30.0.0/24",
                "recommended": True,
            },
            {
                "name": "eth1",
                "ip": "172.30.0.3",
                "status": "Up",
                "network": "172.30.0.0/24",
                "recommended": True,
            },
        ],
    )
    with pytest.raises(ValueError, match="Multiple interfaces found"):
        scanner.select_interface("172.30.0.0/24")
