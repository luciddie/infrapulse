from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.device import Device
from app.repositories.devices import (
    list_devices,
    count_devices
)


router = APIRouter(
    prefix="/api",
    tags=["Devices"]
)


def serialize_device(device: Device) -> dict:
    return {
        "id": device.id,
        "ip_address": device.ip_address,
        "mac_address": device.mac_address,
        "hostname": device.hostname,
        "vendor": device.vendor,
        "status": device.status,
        "first_seen": device.first_seen,
        "last_seen": device.last_seen,
        "created_at": device.created_at,
        "updated_at": device.updated_at
    }


@router.get("/devices")
def get_devices(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    devices = list_devices(
        db,
        limit=limit,
        offset=offset
    )

    return {
        "total": count_devices(db),
        "limit": limit,
        "offset": offset,
        "devices": [
            serialize_device(device)
            for device in devices
        ]
    }


@router.get("/devices/{device_id}")
def get_device(
    device_id: int,
    db: Session = Depends(get_db)
):
    device = db.get(Device, device_id)

    if device is None:
        raise HTTPException(
            status_code=404,
            detail="Device not found"
        )

    return serialize_device(device)