import ipaddress
import json
import argparse

from concurrent.futures import ThreadPoolExecutor

from app.services.icmp import ping_host
from app.services.arp import get_arp_table
from app.services.dns import get_hostname


def get_network_hosts(cidr: str) -> list[str]:
    network = ipaddress.ip_network(
        cidr, strict=False
    )

    if network.version != 4:
        raise ValueError(
            "Only IPv4 networks are supported"
        )

    if network.num_addresses > 256:
        raise ValueError(
            "Network range is too large"
        )

    return [
        str(host) for host in network.hosts()
    ]


def scan_network(
    cidr: str,
    interface_ip: str | None = None,
    resolve_dns: bool = False
) -> list[dict]:

    hosts = get_network_hosts(cidr)

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(
            executor.map(ping_host, hosts)
        )

    arp_table = get_arp_table(interface_ip)

    for device in results:
        ip = device["ip"]

        device["mac"] = arp_table.get(ip)
        device["hostname"] = None

        if (
            resolve_dns
            and device["status"] == "online"
        ):
            device["hostname"] = get_hostname(ip)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="InfraPulse Network Scanner"
    )

    parser.add_argument(
        "network",
        help="IPv4 network in CIDR format"
    )

    parser.add_argument(
        "--interface-ip",
        help="Local network interface IPv4 address"
    )

    parser.add_argument(
        "--resolve-dns",
        action="store_true",
        help="Enable reverse DNS lookups"
    )

    args = parser.parse_args()

    results = scan_network(
        args.network,
        interface_ip=args.interface_ip,
        resolve_dns=args.resolve_dns
    )

    online = [
        device for device in results
        if device["status"] == "online"
    ]

    print(json.dumps(online, indent=4))

    print(f"\nScanned hosts: {len(results)}")
    print(f"Online devices: {len(online)}")
