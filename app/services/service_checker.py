import logging

from time import perf_counter
from ipaddress import IPv4Address
from urllib.parse import urlsplit

from sqlalchemy import select

from app.database import SessionLocal
from app.models.device import Device
from app.models.service import Service

from app.metrics import (
    record_check,
    record_incident
)

from app.repositories.services import create_service_check

from app.services.tcp_checker import check_tcp
from app.services.http_checker import check_http

from app.services.service_incident_manager import (
    process_service_check
)

from app.services.alert_manager import (
    notify_service_incident
)


logger = logging.getLogger("infrapulse.service")


def check_service(service_id: int) -> dict:

    started = perf_counter()

    with SessionLocal() as db:

        service = db.get(Service, service_id)

        if service is None:
            raise ValueError("Service not found")

        if not service.enabled:
            raise ValueError("Service is disabled")

        device = db.get(Device, service.device_id)

        if device is None:
            raise ValueError("Device not found")

        ip_address = str(IPv4Address(device.ip_address))
        protocol = service.protocol
        port = service.port
        url = service.url
        timeout = service.timeout_seconds
        expected_status = service.expected_status

    target = ip_address

    try:

        if protocol == "tcp":

            target = f"{ip_address}:{port}"

            result = check_tcp(
                ip_address,
                port,
                timeout=timeout
            )

        elif protocol == "http":

            parsed = urlsplit(url)

            if parsed.hostname != ip_address:
                raise ValueError(
                    "HTTP target must match device IP"
                )

            target = (
                f"{parsed.scheme}://"
                f"{parsed.hostname}"
            )

            if parsed.port is not None:
                target += f":{parsed.port}"

            target += parsed.path or "/"

            result = check_http(
                url,
                expected_status=expected_status,
                timeout=timeout
            )

        else:
            raise ValueError("Unsupported protocol")

    except Exception as exc:

        result = {
            "status": "unknown",
            "latency_ms": None,
            "status_code": None,
            "error": type(exc).__name__
        }

    with SessionLocal.begin() as db:

        service = db.scalar(
            select(Service)
            .where(Service.id == service_id)
            .with_for_update()
        )

        if service is None:
            raise ValueError("Service not found")

        if not service.enabled:
            raise ValueError("Service is disabled")

        check = create_service_check(
            db,
            service_id,
            result
        )

        service.status = result["status"]

        incident_event = process_service_check(
            db,
            service_id,
            result["status"]
        )

        response = {
            "check_id": check.id,
            "service_id": service_id,
            "device_id": service.device_id,
            "name": service.name,
            "protocol": service.protocol,
            "status": check.status,
            "status_code": check.status_code,
            "latency_ms": check.latency_ms,
            "checked_at": check.checked_at.isoformat(),
            "error": check.error,
            "incident_event": incident_event
        }

    record_check(
        protocol=response["protocol"],
        status=response["status"],
        duration=perf_counter() - started
    )

    if incident_event is not None:

        record_incident(
            incident_type="service",
            event=incident_event
        )

        try:

            notify_service_incident(
                event=incident_event,
                service_id=service_id,
                name=response["name"],
                protocol=response["protocol"],
                target=target,
                status=response["status"]
            )

        except Exception as exc:

            logger.warning(
                "Service notification failed: %s",
                type(exc).__name__
            )

    return response
