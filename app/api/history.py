from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.scan_record import ScanRecord
from app.repositories.scans import list_scans


router = APIRouter(
    prefix="/api",
    tags=["Scan History"]
)


@router.get("/scans")
def get_scan_history(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    scans = list_scans(
        db,
        limit=limit,
        offset=offset
    )

    total = db.scalar(
        select(func.count(ScanRecord.id))
    ) or 0

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "scans": [
            {
                "id": str(scan.id),
                "network": scan.network,
                "status": scan.status,
                "scanned_hosts": scan.scanned_hosts,
                "online_devices": scan.online_devices,
                "created_at": scan.created_at,
                "finished_at": scan.finished_at,
                "error": scan.error
            }
            for scan in scans
        ]
    }