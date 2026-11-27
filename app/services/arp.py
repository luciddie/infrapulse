import subprocess
import platform
import re
import ipaddress


def get_arp_table(interface_ip: str | None = None) -> dict:
    if platform.system() != "Windows":
        return {}

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

    candidates = {}

    for ip, mac in re.findall(
        pattern, output, re.MULTILINE
    ):
        address = ipaddress.IPv4Address(ip)
        mac = mac.upper().replace("-", ":")

        if address.is_multicast:
            continue

        if address.is_unspecified:
            continue

        if mac in (
            "00:00:00:00:00:00",
            "FF:FF:FF:FF:FF:FF"
        ):
            continue

        if int(mac[:2], 16) & 1:
            continue

        candidates.setdefault(ip, set()).add(mac)

    return {
        ip: next(iter(macs))
        for ip, macs in candidates.items()
        if len(macs) == 1
    }
