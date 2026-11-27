import pytest

from uuid import uuid4
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.repositories import devices, scans


def device_data():
    return {
        "ip": "192.0.2.10",
        "mac": "04:F4:1C:00:00:01",
        "vendor": "Test Vendor",
        "hostname": "test-device",
        "status": "online",
        "latency_ms": 2.5,
        "latency_upper_bound_ms": None
    }


def test_create_device():
    with SessionLocal.begin() as db:
        device = devices.upsert_device(
            db, device_data()
        )

        assert device.id is not None
        assert device.ip_address == "192.0.2.10"
        assert device.status == "online"
        assert devices.count_devices(db) == 1


def test_device_no_duplicates():
    with SessionLocal.begin() as db:
        first = devices.upsert_device(
            db, device_data()
        )

        second = devices.upsert_device(
            db, device_data()
        )

        assert first.id == second.id
        assert devices.count_devices(db) == 1


def test_update_device():
    with SessionLocal.begin() as db:
        data = device_data()

        first = devices.upsert_device(db, data)
        first_seen = first.first_seen

        data["hostname"] = "updated-device"

        updated = devices.upsert_device(db, data)

        assert updated.hostname == "updated-device"
        assert updated.first_seen == first_seen


def test_preserve_known_metadata():
    with SessionLocal.begin() as db:
        data = device_data()

        devices.upsert_device(db, data)

        data["mac"] = None
        data["vendor"] = None
        data["hostname"] = None

        updated = devices.upsert_device(db, data)

        assert updated.mac_address == "04:F4:1C:00:00:01"
        assert updated.vendor == "Test Vendor"
        assert updated.hostname == "test-device"


def test_create_scan():
    scan_id = uuid4()

    with SessionLocal.begin() as db:
        scan = scans.create_scan(
            db, scan_id, "192.0.2.0/24"
        )

        assert scan.id == scan_id
        assert scan.status == "pending"


def test_complete_scan():
    scan_id = uuid4()

    with SessionLocal.begin() as db:
        scans.create_scan(
            db, scan_id, "192.0.2.0/24"
        )

        scans.mark_scan_running(db, scan_id)

        scans.complete_scan(
            db, scan_id, [device_data()]
        )

    with SessionLocal() as db:
        scan = scans.get_scan(db, scan_id)

        assert scan.status == "completed"
        assert scan.online_devices == 1
        assert scan.scanned_hosts == 1

        results = scans.get_scan_results(
            db, scan_id
        )

        assert len(results) == 1
        assert results[0].device_id is not None
        assert devices.count_devices(db) == 1


def test_failed_scan():
    scan_id = uuid4()

    with SessionLocal.begin() as db:
        scans.create_scan(
            db, scan_id, "192.0.2.0/24"
        )

        scans.fail_scan(
            db, scan_id, "Test error"
        )

    with SessionLocal() as db:
        scan = scans.get_scan(db, scan_id)

        assert scan.status == "failed"
        assert scan.error == "Test error"


def test_transaction_rollback():
    with pytest.raises(RuntimeError):
        with SessionLocal.begin() as db:
            devices.upsert_device(
                db, device_data()
            )

            raise RuntimeError("Test rollback")

    with SessionLocal() as db:
        assert devices.count_devices(db) == 0


def test_duplicate_scan_result_rollback():
    scan_id = uuid4()

    with SessionLocal.begin() as db:
        scans.create_scan(
            db, scan_id, "192.0.2.0/24"
        )

    with pytest.raises(IntegrityError):
        with SessionLocal.begin() as db:
            scans.complete_scan(
                db,
                scan_id,
                [device_data(), device_data()]
            )

    with SessionLocal() as db:
        assert devices.count_devices(db) == 0
        assert scans.get_scan_results(db, scan_id) == []
        assert scans.get_scan(db, scan_id).status == "pending"
