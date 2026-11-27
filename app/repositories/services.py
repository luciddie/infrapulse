from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.service import Service
from app.models.service_check import ServiceCheck


def create_service(
    db: Session,
    device_id: int,
    name: str,
    protocol: str,
    port: int | None = None,
    url: str | None = None,
    expected_status: int = 200,
    timeout_seconds: float = 3.0
) -> Service:

    service = Service(
        device_id=device_id,
        name=name,
        protocol=protocol,
        port=port,
        url=url,
        expected_status=expected_status,
        timeout_seconds=timeout_seconds,
        enabled=True,
        status="unknown"
    )

    db.add(service)
    db.flush()

    return service


def get_service(
    db: Session,
    service_id: int
) -> Service | None:

    return db.get(Service, service_id)


def list_services(
    db: Session,
    device_id: int | None = None,
    enabled_only: bool = False,
    limit: int = 100,
    offset: int = 0
) -> list[Service]:

    stmt = select(Service)

    if device_id is not None:
        stmt = stmt.where(
            Service.device_id == device_id
        )

    if enabled_only:
        stmt = stmt.where(
            Service.enabled.is_(True)
        )

    stmt = (
        stmt.order_by(Service.id)
        .limit(limit)
        .offset(offset)
    )

    return list(db.scalars(stmt).all())


def create_service_check(
    db: Session,
    service_id: int,
    result: dict
) -> ServiceCheck:

    check = ServiceCheck(
        service_id=service_id,
        status=result["status"],
        status_code=result.get("status_code"),
        latency_ms=result.get("latency_ms"),
        error=result.get("error")
    )

    db.add(check)
    db.flush()

    return check


def list_service_checks(
    db: Session,
    service_id: int,
    limit: int = 100,
    offset: int = 0
) -> list[ServiceCheck]:

    stmt = (
        select(ServiceCheck)
        .where(ServiceCheck.service_id == service_id)
        .order_by(
            ServiceCheck.checked_at.desc(),
            ServiceCheck.id.desc()
        )
        .limit(limit)
        .offset(offset)
    )

    return list(db.scalars(stmt).all())