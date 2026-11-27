import socket


def get_hostname(ip: str) -> str | None:
    try:
        hostname, _, _ = socket.gethostbyaddr(ip)
        return hostname

    except OSError:
        return None
