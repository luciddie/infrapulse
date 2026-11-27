import ipaddress
import subprocess
import platform
import json
import argparse

from concurrent.futures import ThreadPoolExecutor


def get_network_hosts(cidr: str) -> list[str]:
    network = ipaddress.ip_network(cidr, strict=False)

    if network.version != 4:
        raise ValueError("Only IPv4 networks are supported")

    if network.num_addresses > 256:
        raise ValueError("Network range is too large")

    return [str(host) for host in network.hosts()]


def ping_host(ip: str) -> dict:
    ip = str(ipaddress.IPv4Address(ip))
    is_windows = platform.system() == "Windows"

    if is_windows:
        command = ["ping", "-n", "1", "-w", "1000", ip]
    else:
        command = ["ping", "-c", "1", "-W", "1", ip]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=3
        )

        output = result.stdout.lower()

        reachable = result.returncode == 0

        if is_windows:
            reachable = reachable and b"ttl=" in output

        return {
            "ip": ip,
            "status": "online" if reachable else "no_response"
        }

    except (subprocess.TimeoutExpired, OSError):
        return {
            "ip": ip,
            "status": "unknown"
        }


def scan_network(cidr: str) -> list[dict]:
    hosts = get_network_hosts(cidr)

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(ping_host, hosts))

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="InfraPulse Network Scanner"
    )
    parser.add_argument("network", help="IPv4 network in CIDR format")
    args = parser.parse_args()

    results = scan_network(args.network)

    online = [
        device for device in results
        if device["status"] == "online"
    ]

    print(json.dumps(online, indent=4))
    print(f"\nScanned hosts: {len(results)}")
    print(f"Online devices: {len(online)}")