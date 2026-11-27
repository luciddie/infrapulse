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