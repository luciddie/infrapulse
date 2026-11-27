from datetime import datetime, timezone
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query
)
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.incident import Incident
from app.repositories.incidents import list_incidents


router = APIRouter(
    prefix="/api",
    tags=["Incidents"]
)


def serialize_incident(incident: Incident) -> dict:

    end_time = (
        incident.resolved_at
        or datetime.now(timezone.utc)
    )

    duration = (
        end_time - incident.started_at
    ).total_seconds()

    return {
        "id": incident.id,
        "device_id": incident.device_id,
        "status": incident.status,
        "reason": incident.reason,
        "started_at": incident.started_at,
        "resolved_at": incident.resolved_at,
        "duration_seconds": round(duration, 2)
    }


@router.get("/incidents")
def get_incidents(
    status: Literal["open", "resolved"] | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):

    incidents = list_incidents(
        db,
        status=status,
        limit=limit,
        offset=offset
    )

    stmt = select(func.count(Incident.id))

    if status is not None:
        stmt = stmt.where(
            Incident.status == status
        )

    return {
        "total": db.scalar(stmt) or 0,
        "limit": limit,
        "offset": offset,
        "incidents": [
            serialize_incident(incident)
            for incident in incidents
        ]
    }


@router.get("/incidents/summary")
def get_incident_summary(
    db: Session = Depends(get_db)
):

    total = db.scalar(
        select(func.count(Incident.id))
    ) or 0

    opened = db.scalar(
        select(func.count(Incident.id))
        .where(Incident.status == "open")
    ) or 0

    resolved = db.scalar(
        select(func.count(Incident.id))
        .where(Incident.status == "resolved")
    ) or 0

    return {
        "total_incidents": total,
        "open_incidents": opened,
        "resolved_incidents": resolved
    }


@router.get("/incidents/{incident_id}")
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db)
):

    incident = db.get(Incident, incident_id)

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found"
        )

    return serialize_incident(incident)
