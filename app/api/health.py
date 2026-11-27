from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.device import Device
from app.services.health_checker import check_device
from app.repositories.analytics import get_device_analytics
from app.repositories.health_checks import (
    list_health_checks
)


router = APIRouter(
    prefix="/api",
    tags=["Health Monitoring"]
)


@router.post("/devices/{device_id}/check")
def run_health_check(device_id: int):

    try:
        return check_device(device_id)

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc)
        )


@router.get("/devices/{device_id}/health")
def get_device_health(
    device_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):

    if db.get(Device, device_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Device not found"
        )

    checks = list_health_checks(
        db,
        device_id,
        limit=limit,
        offset=offset
    )

    return {
        "device_id": device_id,
        "limit": limit,
        "offset": offset,
        "checks": [
            {
                "id": check.id,
                "status": check.status,
                "latency_ms": check.latency_ms,
                "latency_upper_bound_ms":
                    check.latency_upper_bound_ms,
                "checked_at": check.checked_at,
                "error": check.error
            }
            for check in checks
        ]
    }
@router.get("/devices/{device_id}/analytics")
def get_analytics(
    device_id: int,
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db)
):
    if db.get(Device, device_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Device not found"
        )

    return get_device_analytics(
        db,
        device_id,
        hours=hours
    )