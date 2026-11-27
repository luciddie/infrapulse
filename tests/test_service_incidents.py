import pytest

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models.device import Device
from app.models.service import Service
from app.models.service_check import ServiceCheck
from app.models.service_incident import ServiceIncident

from app.repositories.services import create_service
from app.services import service_checker


@pytest.fixture
def service_id(monkeypatch):

    monkeypatch.setattr(
        settings,
        "service_incident_failure_threshold",
        3
    )

    monkeypatch.setattr(
        settings,
        "telegram_enabled",
        False
    )

    with SessionLocal.begin() as db:

        device = Device(
            ip_address="192.0.2.10",
            status="online"
        )

        db.add(device)
        db.flush()

        service = create_service(
            db,
            device_id=device.id,
            name="Test Service",
            protocol="tcp",
            port=443
        )

        return service.id


def simulate_check(monkeypatch, service_id, status):

    def fake_tcp(*args, **kwargs):

        return {
            "status": status,
            "latency_ms": 10.0 if status == "open" else None,
            "error": None if status == "open" else "Test failure"
        }

    monkeypatch.setattr(
        service_checker,
        "check_tcp",
        fake_tcp
    )

    return service_checker.check_service(service_id)


def get_incidents(service_id):

    with SessionLocal() as db:

        return list(
            db.scalars(
                select(ServiceIncident)
                .where(
                    ServiceIncident.service_id == service_id
                )
                .order_by(ServiceIncident.id)
            ).all()
        )


def test_first_failure(monkeypatch, service_id):

    result = simulate_check(
        monkeypatch, service_id, "closed"
    )

    assert result["incident_event"] is None
    assert len(get_incidents(service_id)) == 0


def test_second_failure(monkeypatch, service_id):

    for _ in range(2):
        result = simulate_check(
            monkeypatch, service_id, "closed"
        )

    assert result["incident_event"] is None
    assert len(get_incidents(service_id)) == 0


def test_incident_opened(monkeypatch, service_id):

    for _ in range(3):
        result = simulate_check(
            monkeypatch, service_id, "closed"
        )

    assert result["incident_event"] == "opened"

    incidents = get_incidents(service_id)

    assert len(incidents) == 1
    assert incidents[0].status == "open"


def test_no_duplicate_incidents(monkeypatch, service_id):

    for _ in range(6):
        simulate_check(
            monkeypatch, service_id, "closed"
        )

    assert len(get_incidents(service_id)) == 1


def test_incident_resolved(monkeypatch, service_id):

    for _ in range(3):
        simulate_check(
            monkeypatch, service_id, "closed"
        )

    result = simulate_check(
        monkeypatch, service_id, "open"
    )

    assert result["incident_event"] == "resolved"

    incidents = get_incidents(service_id)

    assert incidents[0].status == "resolved"
    assert incidents[0].resolved_at is not None


def test_success_resets_sequence(monkeypatch, service_id):

    for status in [
        "closed", "closed", "open", "closed"
    ]:
        simulate_check(
            monkeypatch, service_id, status
        )

    assert len(get_incidents(service_id)) == 0


def test_unknown_resets_sequence(monkeypatch, service_id):

    for status in [
        "closed", "closed", "unknown", "closed"
    ]:
        simulate_check(
            monkeypatch, service_id, status
        )

    assert len(get_incidents(service_id)) == 0


def test_unknown_does_not_resolve(monkeypatch, service_id):

    for _ in range(3):
        simulate_check(
            monkeypatch, service_id, "closed"
        )

    result = simulate_check(
        monkeypatch, service_id, "unknown"
    )

    assert result["incident_event"] is None
    assert get_incidents(service_id)[0].status == "open"


def test_new_incident_after_recovery(monkeypatch, service_id):

    for status in [
        "closed", "closed", "closed",
        "open",
        "closed", "closed", "closed"
    ]:
        simulate_check(
            monkeypatch, service_id, status
        )

    incidents = get_incidents(service_id)

    assert len(incidents) == 2
    assert incidents[0].status == "resolved"
    assert incidents[1].status == "open"


def test_service_status_persisted(monkeypatch, service_id):

    simulate_check(
        monkeypatch, service_id, "open"
    )

    with SessionLocal() as db:

        service = db.get(Service, service_id)

        checks = list(
            db.scalars(
                select(ServiceCheck)
                .where(
                    ServiceCheck.service_id == service_id
                )
            ).all()
        )

        assert service.status == "open"
        assert len(checks) == 1
        assert checks[0].status == "open"
        assert checks[0].latency_ms == 10.0


def test_notifications_after_commit(monkeypatch, service_id):

    events = []

    def fake_notify(**kwargs):

        incidents = get_incidents(service_id)

        events.append((
            kwargs["event"],
            incidents[-1].status
        ))

        return True

    monkeypatch.setattr(
        service_checker,
        "notify_service_incident",
        fake_notify
    )

    for status in [
        "closed", "closed", "closed",
        "closed", "open", "open"
    ]:
        simulate_check(
            monkeypatch, service_id, status
        )

    assert events == [
        ("opened", "open"),
        ("resolved", "resolved")
    ]


def test_notification_failure_preserves_incident(
    monkeypatch, service_id
):

    def fake_notify(**kwargs):
        raise RuntimeError("Telegram unavailable")

    monkeypatch.setattr(
        service_checker,
        "notify_service_incident",
        fake_notify
    )

    for _ in range(3):
        result = simulate_check(
            monkeypatch, service_id, "closed"
        )

    assert result["incident_event"] == "opened"
    assert get_incidents(service_id)[0].status == "open"
