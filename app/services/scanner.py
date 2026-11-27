import ipaddress
import json
import argparse
import platform

from concurrent.futures import ThreadPoolExecutor

from app.services.icmp import ping_host
from app.services.arp import get_arp_table
from app.services.dns import get_hostname
from app.services.vendor import get_vendor
from app.services.interfaces import get_interfaces


def get_network_hosts(cidr: str) -> list[str]:
    network = ipaddress.ip_network(cidr, strict=False)

    if network.version != 4:
        raise ValueError("Only IPv4 networks are supported")

    if network.num_addresses > 4096:
        raise ValueError("Maximum supported network size is /20")

    return [str(host) for host in network.hosts()]

def select_interface(
    cidr: str,
    interface_ip: str | None = None
) -> dict | None:

    if platform.system() != "Windows":
        return None

    network = ipaddress.IPv4Network(cidr, strict=False)

    if network.is_loopback:
        return None

    interfaces = get_interfaces()

    candidates = [
        interface for interface in interfaces
        if interface["status"] == "Up"
        and network.subnet_of(
            ipaddress.IPv4Network(interface["network"])
        )
    ]

    if interface_ip:
        candidates = [
            interface for interface in candidates
            if interface["ip"] == interface_ip
        ]
    else:
        candidates = [
            interface for interface in candidates
            if interface["recommended"]
        ]

    if not candidates:
        raise ValueError("No suitable network interface found")

    if len(candidates) > 1:
        raise ValueError(
            "Multiple interfaces found. Use --interface-ip"
        )

    return candidates[0]


def scan_network(
    cidr: str,
    interface_ip: str | None = None,
    resolve_dns: bool = False,
    workers: int = 8,
    allow_large_scan: bool = False
) -> list[dict]:

    hosts = get_network_hosts(cidr)

    if not 1 <= workers <= 16:
        raise ValueError("Workers must be between 1 and 16")

    if len(hosts) > 254 and not allow_large_scan:
        raise ValueError(
            "Large network scan requires explicit confirmation"
        )

    interface = select_interface(cidr, interface_ip)

    if interface:
        interface_ip = interface["ip"]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(ping_host, hosts))

    arp_table = get_arp_table(interface_ip)

    for device in results:
        ip = device["ip"]

        device["mac"] = arp_table.get(ip)

        if interface and ip == interface["ip"]:
            device["mac"] = interface["mac"]

        device["vendor"] = get_vendor(device["mac"])
        device["hostname"] = None

        if resolve_dns and device["status"] == "online":
            device["hostname"] = get_hostname(ip)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="InfraPulse Network Scanner"
    )

    parser.add_argument(
        "network",
        nargs="?",
        help="IPv4 network in CIDR format"
    )

    parser.add_argument(
        "--interface-ip",
        help="Local network interface IPv4 address"
    )

    parser.add_argument(
        "--resolve-dns",
        action="store_true"
    )

    parser.add_argument(
        "--list-interfaces",
        action="store_true"
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of parallel workers (1-16)"
    )

    parser.add_argument(
        "--allow-large-scan",
        action="store_true",
        help="Explicitly allow scanning large networks"
    )

    args = parser.parse_args()

    if args.list_interfaces:
        print(json.dumps(
            get_interfaces(),
            indent=4,
            ensure_ascii=False
        ))
        return

    if not args.network:
        parser.error("Specify a network or --list-interfaces")

    try:
        results = scan_network(
            args.network,
            interface_ip=args.interface_ip,
            resolve_dns=args.resolve_dns
        )
    except (ValueError, NotImplementedError) as error:
        parser.error(str(error))

    online = [
        device for device in results
        if device["status"] == "online"
    ]

    print(json.dumps(
        online,
        indent=4,
        ensure_ascii=False
    ))

    print(f"\nScanned hosts: {len(results)}")
    print(f"Online devices: {len(online)}")


if __name__ == "__main__":
    main()
