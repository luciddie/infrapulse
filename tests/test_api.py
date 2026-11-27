import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["name"] == "InfraPulse"


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_ready_success(monkeypatch):
    from app import main as app_main

    monkeypatch.setattr(app_main, "check_database", lambda: True)
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "connected"}


def test_ready_failure_and_sanitization(monkeypatch):
    from app import main as app_main

    monkeypatch.setattr(
        app_main,
        "check_database",
        lambda: (_ for _ in ()).throw(
            RuntimeError("postgresql://infrapulse:secret_pw@postgres:5432/infrapulse")
        ),
    )
    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is not ready"}
    assert "secret_pw" not in response.text
    assert "postgresql://" not in response.text

    monkeypatch.setattr(app_main, "check_database", lambda: False)
    response_false = client.get("/ready")
    assert response_false.status_code == 503
    assert response_false.json() == {"detail": "Database is not ready"}


def test_ready_sets_statement_timeout_and_sanitizes_hostname():
    from app import database as app_db

    # Verify check_database executes SET LOCAL statement_timeout = 3000 against infrapulse_test
    assert app_db.check_database() is True

    # Verify /ready never leaks hostname or traceback on OperationalError
    from sqlalchemy.exc import OperationalError
    from app import main as app_main

    def raise_op_error():
        raise OperationalError(
            "SELECT 1",
            {},
            Exception("could not translate host name \"postgres-internal.prod\" to address"),
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(app_main, "check_database", raise_op_error)
        resp = client.get("/ready")

    assert resp.status_code == 503
    assert resp.json() == {"detail": "Database is not ready"}
    assert "postgres-internal" not in resp.text
    assert "Traceback" not in resp.text


def test_invalid_network():
    response = client.post(
        "/api/scan",
        json={"network": "invalid"}
    )

    assert response.status_code == 400


def test_invalid_interface():
    response = client.post(
        "/api/scan",
        json={
            "network": "127.0.0.1/32",
            "interface_ip": "string"
        }
    )

    assert response.status_code == 422


def test_invalid_workers():
    response = client.post(
        "/api/scan",
        json={
            "network": "127.0.0.1/32",
            "workers": 100
        }
    )

    assert response.status_code == 422

def test_large_scan_rejected():
    response = client.post(
        "/api/scan",
        json={"network": "10.0.0.0/20"}
    )

    assert response.status_code == 400


def test_scan_not_found():
    response = client.get("/api/scans/unknown")

    assert response.status_code == 404


def test_results_not_found():
    response = client.get(
        "/api/scans/unknown/results"
    )

    assert response.status_code == 404
def test_successful_scan(monkeypatch):
    import time
    from app.services import scan_manager

    def fake_scan(**kwargs):
        return [
            {
                "ip": "127.0.0.1",
                "status": "online",
                "latency_ms": 1.0,
                "latency_upper_bound_ms": None,
                "mac": None,
                "vendor": None,
                "hostname": None
            }
        ]

    monkeypatch.setattr(
        scan_manager,
        "scan_network",
        fake_scan
    )

    response = client.post(
        "/api/scan",
        json={"network": "127.0.0.1/32"}
    )

    assert response.status_code == 202

    scan_id = response.json()["scan_id"]

    for _ in range(100):
        response = client.get(
            f"/api/scans/{scan_id}"
        )

        status = response.json()["status"]

        if status in ("completed", "failed"):
            break

        time.sleep(0.02)

    assert status == "completed"

    response = client.get(
        f"/api/scans/{scan_id}/results"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["scanned_hosts"] == 1
    assert data["online_devices"] == 1
    assert data["devices"][0]["ip"] == "127.0.0.1"