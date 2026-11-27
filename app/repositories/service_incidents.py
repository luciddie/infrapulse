from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.service_incident import ServiceIncident


def get_open_incident(
    db: Session,
    service_id: int
) -> ServiceIncident | None:

    stmt = select(ServiceIncident).where(
        ServiceIncident.service_id == service_id,
        ServiceIncident.status == "open"
    )

    return db.scalar(stmt)


def create_incident(
    db: Session,
    service_id: int,
    reason: str
) -> ServiceIncident:

    incident = ServiceIncident(
        service_id=service_id,
        status="open",
        reason=reason
    )

    db.add(incident)
    db.flush()

    return incident


def resolve_incident(
    db: Session,
    incident: ServiceIncident
) -> ServiceIncident:

    incident.status = "resolved"
    incident.resolved_at = datetime.now(
        timezone.utc
    )

    db.flush()

    return incident


def list_incidents(
    db: Session,
    service_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0
) -> list[ServiceIncident]:

    stmt = select(ServiceIncident)

    if service_id is not None:
        stmt = stmt.where(
            ServiceIncident.service_id == service_id
        )

    if status is not None:
        stmt = stmt.where(
            ServiceIncident.status == status
        )

    stmt = (
        stmt.order_by(
            ServiceIncident.started_at.desc(),
            ServiceIncident.id.desc()
        )
        .limit(limit)
        .offset(offset)
    )

    return list(db.scalars(stmt).all())