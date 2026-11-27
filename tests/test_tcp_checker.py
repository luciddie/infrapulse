from unittest.mock import MagicMock

import pytest

from app.services import tcp_checker


def test_tcp_open(monkeypatch):
    connection = MagicMock()

    monkeypatch.setattr(
        tcp_checker.socket,
        "create_connection",
        lambda *args, **kwargs: connection
    )

    result = tcp_checker.check_tcp(
        "127.0.0.1", 5432
    )

    assert result["status"] == "open"
    assert result["latency_ms"] is not None
    assert result["error"] is None


def test_tcp_closed(monkeypatch):
    def fake_connect(*args, **kwargs):
        raise ConnectionRefusedError()

    monkeypatch.setattr(
        tcp_checker.socket,
        "create_connection",
        fake_connect
    )

    result = tcp_checker.check_tcp(
        "127.0.0.1", 59999
    )

    assert result["status"] == "closed"


def test_tcp_timeout(monkeypatch):
    def fake_connect(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(
        tcp_checker.socket,
        "create_connection",
        fake_connect
    )

    result = tcp_checker.check_tcp(
        "192.0.2.10", 443
    )

    assert result["status"] == "timeout"


def test_tcp_unknown_error(monkeypatch):
    def fake_connect(*args, **kwargs):
        raise OSError("Network error")

    monkeypatch.setattr(
        tcp_checker.socket,
        "create_connection",
        fake_connect
    )

    result = tcp_checker.check_tcp(
        "192.0.2.10", 443
    )

    assert result["status"] == "unknown"


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_invalid_port(port):
    with pytest.raises(ValueError):
        tcp_checker.check_tcp(
            "127.0.0.1", port
        )


def test_invalid_ip():
    with pytest.raises(ValueError):
        tcp_checker.check_tcp(
            "invalid-ip", 80
        )


@pytest.mark.parametrize("timeout", [0, -1, 11])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        tcp_checker.check_tcp(
            "127.0.0.1",
            80,
            timeout=timeout
        )
