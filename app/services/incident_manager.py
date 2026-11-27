import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.health_check import HealthCheck
from app.repositories.incidents import (
    get_open_incident,
    create_incident,
    resolve_incident
)


logger = logging.getLogger("infrapulse.incidents")


def process_health_check(
    db: Session,
    device_id: int,
    status: str
) -> str | None:

    threshold = settings.incident_failure_threshold

    if not 1 <= threshold <= 100:
        raise ValueError("Invalid incident threshold")

    incident = get_open_incident(db, device_id)

    if status == "online":

        if incident is not None:
            resolve_incident(db, incident)

            return "resolved"

        return None

    if status != "no_response":
        return None

    if incident is not None:
        return None

    stmt = (
        select(HealthCheck.status)
        .where(HealthCheck.device_id == device_id)
        .order_by(
            HealthCheck.checked_at.desc(),
            HealthCheck.id.desc()
        )
        .limit(threshold)
    )

    statuses = list(db.scalars(stmt).all())

    if (
        len(statuses) == threshold
        and all(s == "no_response" for s in statuses)
    ):
        create_incident(
            db,
            device_id,
            reason=f"{threshold} consecutive ICMP failures"
        )

        return "opened"

    return None