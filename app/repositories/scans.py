from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.scan_record import ScanRecord
from app.models.scan_result import ScanResult
from app.repositories.devices import (
    upsert_device,
    get_device_by_ip
)


def create_scan(
    db: Session,
    scan_id: UUID,
    network: str
) -> ScanRecord:
    scan = ScanRecord(
        id=scan_id,
        network=network,
        status="pending"
    )

    db.add(scan)
    db.flush()

    return scan


def get_scan(
    db: Session,
    scan_id: UUID
) -> ScanRecord | None:
    return db.get(ScanRecord, scan_id)


def mark_scan_running(
    db: Session,
    scan_id: UUID
) -> None:
    scan = get_scan(db, scan_id)

    if scan is None:
        raise ValueError("Scan not found")

    scan.status = "running"


def complete_scan(
    db: Session,
    scan_id: UUID,
    results: list[dict]
) -> None:
    scan = get_scan(db, scan_id)

    if scan is None:
        raise ValueError("Scan not found")

    online_count = 0

    for data in results:
        if data["status"] == "online":
            device = upsert_device(db, data)
            online_count += 1
        else:
            device = get_device_by_ip(
                db, data["ip"]
            )

        result = ScanResult(
            scan_id=scan_id,
            device_id=device.id if device else None,
            ip_address=data["ip"],
            mac_address=data.get("mac"),
            hostname=data.get("hostname"),
            vendor=data.get("vendor"),
            status=data["status"],
            latency_ms=data.get("latency_ms"),
            latency_upper_bound_ms=data.get(
                "latency_upper_bound_ms"
            )
        )

        db.add(result)

    scan.status = "completed"
    scan.scanned_hosts = len(results)
    scan.online_devices = online_count
    scan.finished_at = datetime.now(timezone.utc)
    scan.error = None


def fail_scan(
    db: Session,
    scan_id: UUID,
    error: str
) -> None:
    scan = get_scan(db, scan_id)

    if scan is None:
        raise ValueError("Scan not found")

    scan.status = "failed"
    scan.error = error
    scan.finished_at = datetime.now(timezone.utc)


def get_scan_results(
    db: Session,
    scan_id: UUID
) -> list[ScanResult]:
    stmt = (
        select(ScanResult)
        .where(ScanResult.scan_id == scan_id)
        .order_by(ScanResult.id)
    )

    return list(db.scalars(stmt).all())


def list_scans(
    db: Session,
    limit: int = 50,
    offset: int = 0
) -> list[ScanRecord]:
    stmt = (
        select(ScanRecord)
        .order_by(ScanRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    return list(db.scalars(stmt).all())
