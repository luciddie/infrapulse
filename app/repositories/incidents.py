from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.incident import Incident


def get_open_incident(
    db: Session,
    device_id: int
) -> Incident | None:

    stmt = select(Incident).where(
        Incident.device_id == device_id,
        Incident.status == "open"
    )

    return db.scalar(stmt)


def create_incident(
    db: Session,
    device_id: int,
    reason: str
) -> Incident:

    incident = Incident(
        device_id=device_id,
        status="open",
        reason=reason
    )

    db.add(incident)
    db.flush()

    return incident


def resolve_incident(
    db: Session,
    incident: Incident
) -> None:

    incident.status = "resolved"
    incident.resolved_at = datetime.now(
        timezone.utc
    )


def list_incidents(
    db: Session,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0
) -> list[Incident]:

    stmt = select(Incident)

    if status is not None:
        stmt = stmt.where(
            Incident.status == status
        )

    stmt = (
        stmt.order_by(
            Incident.started_at.desc(),
            Incident.id.desc()
        )
        .limit(limit)
        .offset(offset)
    )

    return list(db.scalars(stmt).all())