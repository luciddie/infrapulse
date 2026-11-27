import logging

from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models.device import Device
from app.services.icmp import ping_host
from app.services.incident_manager import process_health_check
from app.services.alert_manager import notify_incident
from app.repositories.health_checks import create_health_check


logger = logging.getLogger("infrapulse.health")


def check_device(device_id: int) -> dict:

    with SessionLocal() as db:
        device = db.get(Device, device_id)

        if device is None:
            raise ValueError("Device not found")

        ip_address = device.ip_address

    try:
        result = ping_host(ip_address)

    except Exception as exc:
        result = {
            "ip": ip_address,
            "status": "unknown",
            "latency_ms": None,
            "latency_upper_bound_ms": None,
            "error": str(exc)
        }

    with SessionLocal.begin() as db:
        device = db.scalar(
            select(Device)
            .where(Device.id == device_id)
            .with_for_update()
        )

        if device is None:
            raise ValueError("Device not found")

        check = create_health_check(
            db,
            device_id,
            result
        )

        device.status = result["status"]

        incident_event = process_health_check(
            db,
            device_id,
            result["status"]
        )

        if result["status"] == "online":
            device.last_seen = datetime.now(
                timezone.utc
            )

        response = {
            "check_id": check.id,
            "device_id": device_id,
            "ip_address": ip_address,
            "status": check.status,
            "latency_ms": check.latency_ms,
            "latency_upper_bound_ms":
                check.latency_upper_bound_ms,
            "checked_at": check.checked_at.isoformat(),
            "error": check.error,
            "incident_event": incident_event
        }

    if incident_event is not None:
        try:
            notify_incident(
                incident_event,
                device_id,
                ip_address
            )
        except Exception as exc:
            logger.warning(
                "Notification failed: %s",
                type(exc).__name__
            )

    return response