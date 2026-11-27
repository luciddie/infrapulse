from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.service_check import ServiceCheck

from app.repositories.service_incidents import (
    get_open_incident,
    create_incident,
    resolve_incident
)


SUCCESS_STATUSES = {
    "open",
    "healthy"
}

FAILURE_STATUSES = {
    "closed",
    "unhealthy",
    "unreachable",
    "timeout"
}


def process_service_check(
    db: Session,
    service_id: int,
    status: str
) -> str | None:

    threshold = settings.service_incident_failure_threshold

    if not 1 <= threshold <= 100:
        raise ValueError(
            "Invalid service incident threshold"
        )

    incident = get_open_incident(
        db,
        service_id
    )

    if status in SUCCESS_STATUSES:

        if incident is not None:
            resolve_incident(db, incident)
            return "resolved"

        return None

    if status not in FAILURE_STATUSES:
        return None

    if incident is not None:
        return None

    stmt = (
        select(ServiceCheck.status)
        .where(ServiceCheck.service_id == service_id)
        .order_by(
            ServiceCheck.checked_at.desc(),
            ServiceCheck.id.desc()
        )
        .limit(threshold)
    )

    statuses = list(db.scalars(stmt).all())

    if (
        len(statuses) == threshold
        and all(
            item in FAILURE_STATUSES
            for item in statuses
        )
    ):

        create_incident(
            db,
            service_id,
            f"{threshold} consecutive service failures"
        )

        return "opened"

    return None