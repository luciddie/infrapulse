from urllib.parse import urlsplit

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.device import Device
from app.models.service_schema import ServiceCreate
from app.repositories.service_analytics import (
    get_service_analytics
)

from app.repositories.services import (
    create_service,
    get_service,
    list_services,
    list_service_checks
)

from app.services.service_checker import check_service


router = APIRouter(
    prefix="/api",
    tags=["Services"]
)


def serialize_service(service):

    return {
        "id": service.id,
        "device_id": service.device_id,
        "name": service.name,
        "protocol": service.protocol,
        "port": service.port,
        "url": service.url,
        "expected_status": service.expected_status,
        "timeout_seconds": service.timeout_seconds,
        "enabled": service.enabled,
        "status": service.status,
        "created_at": service.created_at
    }


@router.post("/services", status_code=201)
def add_service(
    request: ServiceCreate,
    db: Session = Depends(get_db)
):

    device = db.get(Device, request.device_id)

    if device is None:
        raise HTTPException(
            status_code=404,
            detail="Device not found"
        )

    if request.protocol == "http":

        hostname = urlsplit(request.url).hostname

        if hostname != device.ip_address:
            raise HTTPException(
                status_code=400,
                detail="HTTP target must match device IP"
            )

    service = create_service(
        db=db,
        **request.model_dump()
    )

    db.commit()

    return serialize_service(service)


@router.get("/services")
def get_services(
    device_id: int | None = None,
    enabled_only: bool = False,
    limit: int = Query(
        default=100, ge=1, le=500
    ),
    offset: int = Query(
        default=0, ge=0
    ),
    db: Session = Depends(get_db)
):

    services = list_services(
        db,
        device_id=device_id,
        enabled_only=enabled_only,
        limit=limit,
        offset=offset
    )

    return {
        "limit": limit,
        "offset": offset,
        "services": [
            serialize_service(service)
            for service in services
        ]
    }


@router.get("/services/{service_id}")
def get_service_details(
    service_id: int,
    db: Session = Depends(get_db)
):

    service = get_service(db, service_id)

    if service is None:
        raise HTTPException(
            status_code=404,
            detail="Service not found"
        )

    return serialize_service(service)


@router.post("/services/{service_id}/check")
def run_service_check(service_id: int):

    try:
        return check_service(service_id)

    except ValueError as exc:
        detail = str(exc)

        status_code = (
            409 if detail == "Service is disabled"
            else 404
        )

        raise HTTPException(
            status_code=status_code,
            detail=detail
        ) from exc


@router.get("/services/{service_id}/checks")
def get_service_history(
    service_id: int,
    limit: int = Query(
        default=100, ge=1, le=500
    ),
    offset: int = Query(
        default=0, ge=0
    ),
    db: Session = Depends(get_db)
):

    if get_service(db, service_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Service not found"
        )

    checks = list_service_checks(
        db,
        service_id,
        limit=limit,
        offset=offset
    )

    return {
        "service_id": service_id,
        "checks": [
            {
                "id": check.id,
                "status": check.status,
                "status_code": check.status_code,
                "latency_ms": check.latency_ms,
                "error": check.error,
                "checked_at": check.checked_at
            }
            for check in checks
        ]
    }
@router.get("/services/{service_id}/analytics")
def get_analytics(
    service_id: int,
    hours: int = Query(
        default=24,
        ge=1,
        le=720
    ),
    db: Session = Depends(get_db)
):

    service = get_service(db, service_id)

    if service is None:
        raise HTTPException(
            status_code=404,
            detail="Service not found"
        )

    analytics = get_service_analytics(
        db,
        service_id,
        hours
    )

    return {
        "name": service.name,
        "protocol": service.protocol,
        "current_status": service.status,
        **analytics
    }
