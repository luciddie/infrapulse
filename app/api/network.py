from fastapi import APIRouter, HTTPException

from app.models.scan import ScanRequest
from app.services.interfaces import get_interfaces
from app.services.scanner import get_network_hosts, select_interface
from app.services.scan_manager import ScanConflictError, scan_manager


router = APIRouter(
    prefix="/api",
    tags=["Network"]
)


@router.get("/interfaces")
def interfaces():
    try:
        return get_interfaces()
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="Interface discovery is not supported on this platform"
        )
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="Network interface discovery is unavailable"
        )


@router.post("/scan", status_code=202)
def start_scan(request: ScanRequest):

    try:
        hosts = get_network_hosts(request.network)

        if len(hosts) > 254 and not request.allow_large_scan:
            raise ValueError(
                "Large network scan requires explicit confirmation"
            )

        if request.interface_ip is not None:
            select_interface(request.network, request.interface_ip)

        scan_id = scan_manager.start_scan(
            cidr=request.network,
            interface_ip=request.interface_ip,
            resolve_dns=request.resolve_dns,
            workers=request.workers,
            allow_large_scan=request.allow_large_scan
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="Interface discovery is not supported on this platform"
        )

    except ScanConflictError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error)
        )

    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="Network interface discovery is unavailable"
        )

    return {
        "scan_id": scan_id,
        "status_url": f"/api/scans/{scan_id}"
    }


@router.get("/scans/{scan_id}")
def scan_status(scan_id: str):

    scan = scan_manager.get_scan(scan_id)

    if not scan:
        raise HTTPException(
            status_code=404,
            detail="Scan not found"
        )

    return {
        key: value
        for key, value in scan.items()
        if key != "results"
    }


@router.get("/scans/{scan_id}/results")
def scan_results(scan_id: str):

    scan = scan_manager.get_scan(scan_id)

    if not scan:
        raise HTTPException(
            status_code=404,
            detail="Scan not found"
        )

    if scan["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail="Scan is not completed"
        )

    results = scan["results"]

    online = [
        device for device in results
        if device["status"] == "online"
    ]

    return {
        "scan_id": scan_id,
        "scanned_hosts": len(results),
        "online_devices": len(online),
        "devices": online
    }
