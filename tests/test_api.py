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