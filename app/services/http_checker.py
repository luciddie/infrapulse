import time

import httpx

from urllib.parse import urlsplit


def check_http(
    url: str,
    expected_status: int = 200,
    timeout: float = 5.0
) -> dict:

    parsed = urlsplit(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("Invalid URL scheme")

    if not parsed.hostname:
        raise ValueError("Invalid hostname")

    if parsed.username or parsed.password:
        raise ValueError("Credentials in URL are not allowed")

    if not 100 <= expected_status <= 599:
        raise ValueError("Invalid expected status")

    if not 0 < timeout <= 15:
        raise ValueError("Invalid timeout")

    result = {
        "url": url,
        "protocol": "http",
        "status": "unknown",
        "status_code": None,
        "expected_status": expected_status,
        "latency_ms": None,
        "error": None
    }

    started = time.perf_counter()

    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False
        ) as client:

            with client.stream("GET", url) as response:

                result["status_code"] = response.status_code

                result["latency_ms"] = round(
                    (time.perf_counter() - started) * 1000,
                    2
                )

                if response.status_code == expected_status:
                    result["status"] = "healthy"

                else:
                    result["status"] = "unhealthy"
                    result["error"] = (
                        f"Expected HTTP {expected_status}, "
                        f"received {response.status_code}"
                    )

    except httpx.TimeoutException:
        result["status"] = "timeout"
        result["error"] = "HTTP request timed out"

    except httpx.ConnectError:
        result["status"] = "unreachable"
        result["error"] = "Connection failed"

    except httpx.HTTPError as exc:
        result["status"] = "unknown"
        result["error"] = type(exc).__name__

    return result
