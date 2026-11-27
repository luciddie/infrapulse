import ipaddress
import json
import platform
import re
import subprocess

from app.services.interfaces import get_interfaces


_MAC_PATTERN = re.compile(
    r"^[0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5}$"
)
_UNUSABLE_NEIGH_STATES = frozenset({
    "FAILED",
    "INCOMPLETE",
    "NOARP",
    "NONE",
})


def _filter_arp_candidates(
    pairs: list[tuple[str, str]],
) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}

    for raw_ip, raw_mac in pairs:
        if not isinstance(raw_ip, str) or not isinstance(raw_mac, str):
            continue

        mac_str = raw_mac.strip()
        if not _MAC_PATTERN.fullmatch(mac_str):
            continue

        try:
            address = ipaddress.IPv4Address(raw_ip.strip())
        except ValueError:
            continue

        if address.is_multicast or address.is_unspecified:
            continue

        mac = mac_str.upper().replace("-", ":")
        if mac in (
            "00:00:00:00:00:00",
            "FF:FF:FF:FF:FF:FF",
        ):
            continue

        if int(mac[:2], 16) & 1:
            continue

        candidates.setdefault(str(address), set()).add(mac)

    return {
        ip: next(iter(macs))
        for ip, macs in candidates.items()
        if len(macs) == 1
    }


def _get_windows_arp_table(
    interface_ip: str | None = None,
) -> dict[str, str]:
    command = ["arp", "-a"]

    if interface_ip:
        interface_ip = str(
            ipaddress.IPv4Address(interface_ip)
        )
        command.extend(["-N", interface_ip])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=5
        )

        if result.returncode != 0:
            return {}

        output = result.stdout.decode(
            errors="ignore"
        )

    except (subprocess.TimeoutExpired, OSError):
        return {}

    pattern = (
        r"^\s*(\d+\.\d+\.\d+\.\d+)"
        r"\s+([0-9a-fA-F]{2}"
        r"(?:[:-][0-9a-fA-F]{2}){5})"
    )

    pairs = re.findall(pattern, output, re.MULTILINE)
    return _filter_arp_candidates(pairs)


def _resolve_linux_interface_name(
    interface_ip: str,
) -> str | None:
    target_ip = str(ipaddress.IPv4Address(interface_ip))

    try:
        interfaces = get_interfaces()
    except (NotImplementedError, RuntimeError):
        return None

    for interface in interfaces:
        if interface.get("ip") == target_ip:
            name = interface.get("name")
            if isinstance(name, str) and name:
                return name

    return None


def _parse_neigh_states(raw_state: object) -> set[str]:
    if isinstance(raw_state, str):
        return {token.upper() for token in raw_state.split() if token}
    if isinstance(raw_state, list):
        return {
            str(item).upper()
            for item in raw_state
            if isinstance(item, str) and item.strip()
        }
    return set()


def _get_linux_arp_table(
    interface_ip: str | None = None,
    interface_name: str | None = None,
) -> dict[str, str]:
    """Read the Linux kernel IPv4 neighbour cache via `ip -j neigh show`.

    Note: This inspects the OS neighbour cache rather than performing
    privileged raw-socket ARP scanning. In Docker bridge mode, only L2
    neighbours on the container's bridge subnet are visible.
    """
    command = ["ip", "-j", "neigh", "show"]

    if interface_name:
        command.extend(["dev", interface_name])
    elif interface_ip:
        ifname = _resolve_linux_interface_name(interface_ip)
        if not ifname:
            return {}
        command.extend(["dev", ifname])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if result.returncode != 0:
            return {}
        entries = json.loads(result.stdout)
    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
        OSError,
        json.JSONDecodeError,
    ):
        return {}

    if not isinstance(entries, list):
        return {}

    pairs: list[tuple[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        dst = entry.get("dst")
        lladdr = entry.get("lladdr")
        if not isinstance(dst, str) or not isinstance(lladdr, str):
            continue

        states = _parse_neigh_states(entry.get("state"))
        if not states or states & _UNUSABLE_NEIGH_STATES:
            continue

        pairs.append((dst, lladdr))

    return _filter_arp_candidates(pairs)


def get_arp_table(
    interface_ip: str | None = None,
    interface_name: str | None = None,
) -> dict[str, str]:
    system = platform.system()
    if system == "Windows":
        return _get_windows_arp_table(interface_ip)
    if system == "Linux":
        return _get_linux_arp_table(interface_ip, interface_name=interface_name)
    return {}
