import pytest

from sqlalchemy import select, func

from app.config import settings
from app.database import SessionLocal
from app.models.incident import Incident
from app.repositories.devices import upsert_device
from app.repositories.incidents import get_open_incident
from app.services import health_checker


@pytest.fixture
def device_id(monkeypatch):
    monkeypatch.setattr(
        settings,
        "incident_failure_threshold",
        3
    )

    with SessionLocal.begin() as db:
        device = upsert_device(db, {
            "ip": "192.0.2.10",
            "status": "online"
        })

        return device.id


def simulate_check(monkeypatch, device_id, status):

    def fake_ping(ip):
        return {
            "ip": ip,
            "status": status,
            "latency_ms": 2.0 if status == "online" else None,
            "latency_upper_bound_ms": None
        }

    monkeypatch.setattr(
        health_checker,
        "ping_host",
        fake_ping
    )

    return health_checker.check_device(device_id)


def test_first_failure(monkeypatch, device_id):
    result = simulate_check(
        monkeypatch, device_id, "no_response"
    )

    assert result["incident_event"] is None


def test_second_failure(monkeypatch, device_id):
    for _ in range(2):
        result = simulate_check(
            monkeypatch, device_id, "no_response"
        )

    assert result["incident_event"] is None

    with SessionLocal() as db:
        assert get_open_incident(db, device_id) is None


def test_incident_opened(monkeypatch, device_id):
    for _ in range(3):
        result = simulate_check(
            monkeypatch, device_id, "no_response"
        )

    assert result["incident_event"] == "opened"

    with SessionLocal() as db:
        incident = get_open_incident(db, device_id)

        assert incident is not None
        assert incident.status == "open"


def test_no_duplicate_incidents(monkeypatch, device_id):
    for _ in range(5):
        simulate_check(
            monkeypatch, device_id, "no_response"
        )

    with SessionLocal() as db:
        total = db.scalar(
            select(func.count(Incident.id))
        )

        assert total == 1


def test_incident_resolved(monkeypatch, device_id):
    for _ in range(3):
        simulate_check(
            monkeypatch, device_id, "no_response"
        )

    result = simulate_check(
        monkeypatch, device_id, "online"
    )

    assert result["incident_event"] == "resolved"

    with SessionLocal() as db:
        incident = db.scalar(select(Incident))

        assert incident.status == "resolved"
        assert incident.resolved_at is not None


def test_unknown_does_not_open_incident(
    monkeypatch, device_id
):
    for _ in range(3):
        simulate_check(
            monkeypatch, device_id, "unknown"
        )

    with SessionLocal() as db:
        assert get_open_incident(db, device_id) is None


def test_success_resets_failure_sequence(
    monkeypatch, device_id
):
    for status in [
        "no_response",
        "no_response",
        "online",
        "no_response",
        "no_response"
    ]:
        simulate_check(
            monkeypatch, device_id, status
        )

    with SessionLocal() as db:
        assert get_open_incident(db, device_id) is None


def test_unknown_does_not_resolve_incident(
    monkeypatch, device_id
):
    for _ in range(3):
        simulate_check(
            monkeypatch, device_id, "no_response"
        )

    simulate_check(
        monkeypatch, device_id, "unknown"
    )

    with SessionLocal() as db:
        assert get_open_incident(db, device_id) is not None


def test_new_incident_after_recovery(
    monkeypatch, device_id
):
    for status in [
        "no_response",
        "no_response",
        "no_response",
        "online",
        "no_response",
        "no_response",
        "no_response"
    ]:
        simulate_check(
            monkeypatch, device_id, status
        )

    with SessionLocal() as db:
        incidents = list(
            db.scalars(
                select(Incident).order_by(Incident.id)
            ).all()
        )

        assert len(incidents) == 2
        assert incidents[0].status == "resolved"
        assert incidents[1].status == "open"
