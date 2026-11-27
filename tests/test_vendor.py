from app.services.vendor import get_vendor
from app.services import vendor


def test_known_vendor(monkeypatch):
    monkeypatch.setattr(
        vendor,
        "load_oui_database",
        lambda: {"04F41C": "Routerboard.com"}
    )

    assert get_vendor(
        "04:F4:1C:00:00:01"
    ) == "Routerboard.com"


def test_missing_mac():
    assert get_vendor(None) is None


def test_invalid_mac():
    assert get_vendor("invalid") is None


def test_locally_administered_mac():
    assert get_vendor("02:00:00:00:00:01") is None


def test_unknown_vendor(monkeypatch):
    monkeypatch.setattr(
        vendor,
        "load_oui_database",
        lambda: {}
    )

    assert get_vendor("04:F4:1C:00:00:01") is None