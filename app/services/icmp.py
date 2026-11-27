import ipaddress
import platform
import re
import subprocess


def ping_host(ip: str) -> dict:
    ip = str(ipaddress.IPv4Address(ip))
    is_windows = platform.system() == "Windows"

    if is_windows:
        command = ["ping", "-n", "1", "-w", "1000", ip]
    else:
        command = ["ping", "-c", "1", "-W", "1", ip]

    result_data = {
        "ip": ip,
        "status": "unknown",
        "latency_ms": None,
        "latency_upper_bound_ms": None
    }

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

        result_data["status"] = (
            "online" if reachable else "no_response"
        )

        if reachable:
            match = re.search(
                rb"time\s*([=<])\s*(\d+(?:[.,]\d+)?)\s*ms",
                output
            )

            if match:
                value = float(
                    match.group(2).replace(b",", b".")
                )

                if match.group(1) == b"<":
                    result_data["latency_upper_bound_ms"] = value
                else:
                    result_data["latency_ms"] = value

    except (subprocess.TimeoutExpired, OSError):
        pass

    return result_data
