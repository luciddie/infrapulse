import ipaddress
import json
import platform
import re
import subprocess
from pathlib import Path


_VIRTUAL_INFO_KINDS = frozenset({
    "bond",
    "bridge",
    "dummy",
    "gre",
    "gretap",
    "ifb",
    "ip6tnl",
    "ipip",
    "macvlan",
    "macvtap",
    "sit",
    "tap",
    "tun",
    "veth",
    "vlan",
    "vti",
    "vxlan",
    "wireguard",
})


_MAC_PATTERN = re.compile(
    r"^[0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5}$"
)


def _normalize_mac(mac: str | None) -> str | None:
    if not isinstance(mac, str):
        return None
    stripped = mac.strip()
    if not stripped or not _MAC_PATTERN.fullmatch(stripped):
        return None
    return stripped.replace("-", ":").upper()


def _run_ip_json(args: list[str]) -> list:
    try:
        result = subprocess.run(
            ["ip", "-j", *args],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "iproute2 'ip' command is not available"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Linux network discovery command timed out"
        ) from exc
    except (subprocess.CalledProcessError, OSError) as exc:
        raise RuntimeError(
            "Linux network discovery command failed"
        ) from exc

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Invalid JSON output from iproute2"
        ) from exc

    if not isinstance(data, list):
        raise RuntimeError(
            "Unexpected JSON structure from iproute2"
        )

    return data


def _is_linux_physical_interface(
    ifname: str,
    link_type: str | None,
    flags: list,
    info_kind: str | None,
) -> bool:
    if link_type == "loopback" or "LOOPBACK" in flags:
        return False

    if info_kind and info_kind.lower() in _VIRTUAL_INFO_KINDS:
        return False

    if info_kind:
        return False

    try:
        sysfs_net = Path("/sys/class/net")
        if sysfs_net.exists():
            iface_path = sysfs_net / ifname
            if iface_path.exists():
                return (iface_path / "device").exists()
    except OSError:
        pass

    return link_type == "ether"


def _extract_default_gateways(routes: list) -> dict[str, str]:
    best_routes: dict[str, tuple[int, int, str]] = {}

    for idx, route in enumerate(routes):
        if not isinstance(route, dict):
            continue

        if route.get("dst") != "default":
            continue

        dev = route.get("dev")
        gateway = route.get("gateway")

        if not isinstance(dev, str) or not isinstance(gateway, str):
            continue

        try:
            gateway_ip = str(ipaddress.IPv4Address(gateway))
        except ValueError:
            continue

        raw_metric = route.get("metric")
        metric = (
            raw_metric
            if isinstance(raw_metric, int) and not isinstance(raw_metric, bool)
            else 0
        )

        candidate = (metric, idx, gateway_ip)
        current = best_routes.get(dev)
        if current is None or candidate < current:
            best_routes[dev] = candidate

    return {dev: entry[2] for dev, entry in best_routes.items()}


def _get_linux_interfaces() -> list[dict]:
    addresses = _run_ip_json(["address", "show"])
    links = _run_ip_json(["link", "show"])
    routes = _run_ip_json(["route", "show"])

    links_by_index: dict[int, dict] = {}
    links_by_name: dict[str, dict] = {}
    for link in links:
        if not isinstance(link, dict):
            continue
        if isinstance(link.get("ifindex"), int):
            links_by_index[link["ifindex"]] = link
        if isinstance(link.get("ifname"), str):
            links_by_name[link["ifname"]] = link

    gateways = _extract_default_gateways(routes)
    interfaces: list[dict] = []

    for entry in addresses:
        if not isinstance(entry, dict):
            continue

        ifname = entry.get("ifname")
        ifindex = entry.get("ifindex")
        addr_info = entry.get("addr_info")

        if not isinstance(ifname, str) or not isinstance(addr_info, list):
            continue

        link = (
            links_by_index.get(ifindex)
            if isinstance(ifindex, int)
            else None
        ) or links_by_name.get(ifname) or {}

        flags = entry.get("flags")
        if not isinstance(flags, list):
            flags = link.get("flags") if isinstance(link.get("flags"), list) else []

        operstate = str(
            entry.get("operstate") or link.get("operstate") or ""
        ).upper()
        is_up = operstate == "UP" or (
            operstate == "UNKNOWN" and "UP" in flags and "LOWER_UP" in flags
        )
        status = "Up" if is_up else "Down"

        link_type = entry.get("link_type") or link.get("link_type")
        linkinfo = link.get("linkinfo")
        info_kind = (
            linkinfo.get("info_kind")
            if isinstance(linkinfo, dict) and isinstance(linkinfo.get("info_kind"), str)
            else None
        )

        physical = _is_linux_physical_interface(
            ifname=ifname,
            link_type=link_type if isinstance(link_type, str) else None,
            flags=flags,
            info_kind=info_kind,
        )

        mac = _normalize_mac(entry.get("address") or link.get("address"))
        if mac == "00:00:00:00:00:00":
            mac = None

        description = info_kind or (
            link_type if isinstance(link_type, str) else None
        )

        for addr in addr_info:
            if not isinstance(addr, dict) or addr.get("family") != "inet":
                continue

            local_ip = addr.get("local")
            prefix = addr.get("prefixlen")
            if (
                not isinstance(local_ip, str)
                or not isinstance(prefix, int)
                or isinstance(prefix, bool)
            ):
                continue

            try:
                iface = ipaddress.IPv4Interface(f"{local_ip}/{prefix}")
            except ValueError:
                continue

            recommended = (
                status == "Up"
                and not iface.ip.is_link_local
                and not iface.ip.is_loopback
                and not iface.ip.is_unspecified
            )

            interfaces.append({
                "name": ifname,
                "index": ifindex,
                "ip": str(iface.ip),
                "prefix": prefix,
                "gateway": gateways.get(ifname),
                "mac": mac,
                "status": status,
                "physical": physical,
                "description": description,
                "network": str(iface.network),
                "netmask": str(iface.netmask),
                "recommended": recommended,
            })

    return interfaces


def _get_windows_interfaces() -> list[dict]:
    script = r"""
    $ErrorActionPreference = 'Stop'
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8

    $items = @(
        foreach ($config in Get-NetIPConfiguration) {
            $adapter = Get-NetAdapter -IncludeHidden |
                Where-Object {
                    $_.InterfaceIndex -eq $config.InterfaceIndex
                } | Select-Object -First 1

            foreach ($address in $config.IPv4Address) {
                [PSCustomObject]@{
                    name = $config.InterfaceAlias
                    index = $config.InterfaceIndex
                    ip = $address.IPAddress
                    prefix = $address.PrefixLength
                    gateway = @(
                        $config.IPv4DefaultGateway |
                        ForEach-Object { $_.NextHop }
                    ) | Select-Object -First 1
                    mac = $adapter.MacAddress
                    status = [string]$adapter.Status
                    physical = [bool]$adapter.HardwareInterface
                    description = $adapter.InterfaceDescription
                }
            }
        }
    )

    ConvertTo-Json -InputObject $items -Depth 3 -Compress
    """

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script
        ],
        capture_output=True,
        encoding="utf-8",
        timeout=30,
        check=True
    )

    interfaces = json.loads(result.stdout)

    for interface in interfaces:
        if not isinstance(interface.get("gateway"), str):
            interface["gateway"] = None
        address = ipaddress.IPv4Interface(
            f"{interface['ip']}/{interface['prefix']}"
        )

        interface["network"] = str(address.network)
        interface["netmask"] = str(address.netmask)

        interface["mac"] = _normalize_mac(interface.get("mac"))

        interface["recommended"] = (
            interface["status"] == "Up"
            and interface["physical"]
            and not address.ip.is_link_local
            and not address.ip.is_loopback
            and not address.ip.is_unspecified
        )

    return interfaces


def get_interfaces() -> list[dict]:
    system = platform.system()
    if system == "Windows":
        return _get_windows_interfaces()
    if system == "Linux":
        return _get_linux_interfaces()
    raise NotImplementedError(
        f"Interface discovery is not supported on {system}"
    )


def get_recommended_interfaces() -> list[dict]:
    return [
        interface
        for interface in get_interfaces()
        if interface["recommended"]
    ]


if __name__ == "__main__":
    interfaces = get_interfaces()

    print(json.dumps(
        interfaces,
        indent=4,
        ensure_ascii=False
    ))
