from app.services import alert_manager
from app.services import telegram
from app.config import settings


def test_incident_open_notification(monkeypatch):
    messages = []

    def fake_send(message):
        messages.append(message)
        return True

    monkeypatch.setattr(
        alert_manager,
        "send_message",
        fake_send
    )

    result = alert_manager.notify_incident(
        "opened", 1, "192.0.2.10"
    )

    assert result is True
    assert len(messages) == 1
    assert "INCIDENT DETECTED" in messages[0]
    assert "192.0.2.10" in messages[0]


def test_incident_resolved_notification(monkeypatch):
    messages = []

    def fake_send(message):
        messages.append(message)
        return True

    monkeypatch.setattr(
        alert_manager,
        "send_message",
        fake_send
    )

    result = alert_manager.notify_incident(
        "resolved", 1, "192.0.2.10"
    )

    assert result is True
    assert len(messages) == 1
    assert "INCIDENT RESOLVED" in messages[0]


def test_unknown_event(monkeypatch):
    def fake_send(message):
        raise AssertionError("Unexpected notification")

    monkeypatch.setattr(
        alert_manager,
        "send_message",
        fake_send
    )

    assert alert_manager.notify_incident(
        "unknown", 1, "192.0.2.10"
    ) is False


def test_telegram_disabled(monkeypatch):
    monkeypatch.setattr(
        settings,
        "telegram_enabled",
        False
    )

    assert telegram.send_message("Test") is False


def test_telegram_missing_token(monkeypatch):
    monkeypatch.setattr(
        settings,
        "telegram_enabled",
        True
    )

    monkeypatch.setattr(
        settings,
        "telegram_bot_token",
        None
    )

    assert telegram.send_message("Test") is False
