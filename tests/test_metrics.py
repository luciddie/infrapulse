from fastapi.testclient import TestClient

from prometheus_client import REGISTRY

from app.main import app
from app.database import SessionLocal
from app.models.device import Device

from app.metrics import (
    record_check,
    record_incident,
    record_monitoring_cycle
)

from app.services.metrics_collector import (
    collect_database_metrics
)


def metric_value(name, labels=None):
    return REGISTRY.get_sample_value(
        name,
        labels or {}
    ) or 0.0


def test_metrics_endpoint():
    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "infrapulse_app_info" in response.text
    assert "infrapulse_devices_total" in response.text


def test_metrics_content_type():
    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.headers[
        "content-type"
    ].startswith("text/plain")


def test_check_counter():
    labels = {
        "protocol": "icmp",
        "status": "online"
    }

    before = metric_value(
        "infrapulse_checks_total",
        labels
    )

    record_check("icmp", "online", 0.05)

    after = metric_value(
        "infrapulse_checks_total",
        labels
    )

    assert after == before + 1


def test_check_histogram():
    labels = {"protocol": "tcp"}

    before = metric_value(
        "infrapulse_check_duration_seconds_count",
        labels
    )

    record_check("tcp", "open", 0.1)

    after = metric_value(
        "infrapulse_check_duration_seconds_count",
        labels
    )

    assert after == before + 1


def test_incident_counter():
    labels = {
        "type": "device",
        "event": "opened"
    }

    before = metric_value(
        "infrapulse_incident_events_total",
        labels
    )

    record_incident("device", "opened")

    after = metric_value(
        "infrapulse_incident_events_total",
        labels
    )

    assert after == before + 1


def test_monitoring_cycle_counter():
    labels = {"status": "success"}

    before = metric_value(
        "infrapulse_monitoring_cycles_total",
        labels
    )

    record_monitoring_cycle("success", 0.2)

    after = metric_value(
        "infrapulse_monitoring_cycles_total",
        labels
    )

    assert after == before + 1


def test_database_devices_gauge():
    with SessionLocal.begin() as db:
        db.add(
            Device(
                ip_address="192.0.2.10",
                status="online"
            )
        )

    collect_database_metrics()

    assert metric_value(
        "infrapulse_devices_total"
    ) == 1


def test_empty_database_metrics():
    collect_database_metrics()

    assert metric_value(
        "infrapulse_devices_total"
    ) == 0

    assert metric_value(
        "infrapulse_services_total"
    ) == 0

    assert metric_value(
        "infrapulse_open_incidents",
        {"type": "device"}
    ) == 0

    assert metric_value(
        "infrapulse_open_incidents",
        {"type": "service"}
    ) == 0


def test_metrics_database_failure(monkeypatch):
    from app.api import metrics

    def failing_collector():
        raise RuntimeError("Database unavailable")

    monkeypatch.setattr(
        metrics,
        "collect_database_metrics",
        failing_collector
    )

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 503
