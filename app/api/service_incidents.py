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
from app.models.service_incident import ServiceIncident

from app.repositories.service_incidents import (
    list_incidents
)


router = APIRouter(
    prefix="/api",
    tags=["Service Incidents"]
)


def serialize_incident(incident):

    end_time = (
        incident.resolved_at
        or datetime.now(timezone.utc)
    )

    duration = (
        end_time - incident.started_at
    ).total_seconds()

    return {
        "id": incident.id,
        "service_id": incident.service_id,
        "status": incident.status,
        "reason": incident.reason,
        "started_at": incident.started_at,
        "resolved_at": incident.resolved_at,
        "duration_seconds": round(duration, 2)
    }


@router.get("/service-incidents")
def get_incidents(
    service_id: int | None = None,
    status: Literal["open", "resolved"] | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):

    incidents = list_incidents(
        db,
        service_id=service_id,
        status=status,
        limit=limit,
        offset=offset
    )

    stmt = select(func.count(ServiceIncident.id))

    if service_id is not None:
        stmt = stmt.where(
            ServiceIncident.service_id == service_id
        )

    if status is not None:
        stmt = stmt.where(
            ServiceIncident.status == status
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


@router.get("/service-incidents/summary")
def get_summary(db: Session = Depends(get_db)):

    total = db.scalar(
        select(func.count(ServiceIncident.id))
    ) or 0

    opened = db.scalar(
        select(func.count(ServiceIncident.id))
        .where(ServiceIncident.status == "open")
    ) or 0

    resolved = db.scalar(
        select(func.count(ServiceIncident.id))
        .where(ServiceIncident.status == "resolved")
    ) or 0

    return {
        "total_incidents": total,
        "open_incidents": opened,
        "resolved_incidents": resolved
    }


@router.get("/service-incidents/{incident_id}")
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db)
):

    incident = db.get(
        ServiceIncident,
        incident_id
    )

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Service incident not found"
        )

    return serialize_incident(incident)
