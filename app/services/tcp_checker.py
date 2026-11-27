import socket
import time

from ipaddress import IPv4Address


def check_tcp(
    ip_address: str,
    port: int,
    timeout: float = 3.0
) -> dict:

    ip_address = str(IPv4Address(ip_address))

    if not 1 <= port <= 65535:
        raise ValueError("Invalid TCP port")

    if not 0 < timeout <= 10:
        raise ValueError("Invalid timeout")

    result = {
        "ip_address": ip_address,
        "port": port,
        "protocol": "tcp",
        "status": "unknown",
        "latency_ms": None,
        "error": None
    }

    started = time.perf_counter()

    try:
        with socket.create_connection(
            (ip_address, port),
            timeout=timeout
        ):
            result["status"] = "open"

            result["latency_ms"] = round(
                (time.perf_counter() - started) * 1000,
                2
            )

    except ConnectionRefusedError:
        result["status"] = "closed"
        result["error"] = "Connection refused"

    except TimeoutError:
        result["status"] = "timeout"
        result["error"] = "Connection timed out"

    except OSError as exc:
        result["status"] = "unknown"
        result["error"] = str(exc)

    return result