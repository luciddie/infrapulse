import pytest

from app.services.scanner import (
    get_network_hosts,
    scan_network
)


def test_network_24():
    hosts = get_network_hosts("192.0.2.0/24")

    assert len(hosts) == 254
    assert hosts[0] == "192.0.2.1"
    assert hosts[-1] == "192.0.2.254"


def test_network_20():
    hosts = get_network_hosts("10.0.0.0/20")

    assert len(hosts) == 4094


def test_single_host():
    hosts = get_network_hosts("127.0.0.1/32")

    assert hosts == ["127.0.0.1"]


def test_invalid_network():
    with pytest.raises(ValueError):
        get_network_hosts("invalid")


def test_ipv6_rejected():
    with pytest.raises(ValueError):
        get_network_hosts("::1/128")


def test_network_too_large():
    with pytest.raises(ValueError):
        get_network_hosts("10.0.0.0/16")


def test_large_scan_requires_confirmation():
    with pytest.raises(ValueError, match="confirmation"):
        scan_network("10.0.0.0/20")


def test_invalid_workers():
    with pytest.raises(ValueError, match="Workers"):
        scan_network("127.0.0.1/32", workers=100)


def test_zero_workers():
    with pytest.raises(ValueError, match="Workers"):
        scan_network("127.0.0.1/32", workers=0)