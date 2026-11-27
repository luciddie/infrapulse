from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import UUID, uuid4

from app.database import SessionLocal
from app.services.scanner import scan_network
from app.repositories import scans


class ScanManager:

    def __init__(self):
        self.lock = Lock()
        self.executor = ThreadPoolExecutor(
            max_workers=1
        )
        self.active_scan_id = None

    def start_scan(self, **params) -> str:
        with self.lock:
            if self.active_scan_id is not None:
                raise RuntimeError(
                    "Another scan is already running"
                )

            scan_id = uuid4()

            with SessionLocal.begin() as db:
                scans.create_scan(
                    db,
                    scan_id,
                    params["cidr"]
                )

            self.active_scan_id = scan_id

            try:
                self.executor.submit(
                    self._run_scan,
                    scan_id,
                    params
                )
            except Exception as exc:
                self.active_scan_id = None

                with SessionLocal.begin() as db:
                    scans.fail_scan(
                        db, scan_id, str(exc)
                    )

                raise

            return str(scan_id)

    def _run_scan(
        self,
        scan_id: UUID,
        params: dict
    ) -> None:

        try:
            with SessionLocal.begin() as db:
                scans.mark_scan_running(
                    db, scan_id
                )

            results = scan_network(**params)

            with SessionLocal.begin() as db:
                scans.complete_scan(
                    db,
                    scan_id,
                    results
                )

        except Exception as exc:
            with SessionLocal.begin() as db:
                scans.fail_scan(
                    db,
                    scan_id,
                    str(exc)
                )

        finally:
            with self.lock:
                self.active_scan_id = None

    def get_scan(
        self,
        scan_id: str
    ) -> dict | None:

        try:
            scan_uuid = UUID(scan_id)
        except ValueError:
            return None

        with SessionLocal() as db:
            scan = scans.get_scan(
                db, scan_uuid
            )

            if scan is None:
                return None

            results = None

            if scan.status == "completed":
                records = scans.get_scan_results(
                    db, scan_uuid
                )

                results = [
                    {
                        "ip": record.ip_address,
                        "mac": record.mac_address,
                        "hostname": record.hostname,
                        "vendor": record.vendor,
                        "status": record.status,
                        "latency_ms": record.latency_ms,
                        "latency_upper_bound_ms":
                            record.latency_upper_bound_ms
                    }
                    for record in records
                ]

            return {
                "id": str(scan.id),
                "network": scan.network,
                "status": scan.status,
                "created_at": scan.created_at.isoformat(),
                "finished_at": (
                    scan.finished_at.isoformat()
                    if scan.finished_at
                    else None
                ),
                "error": scan.error,
                "results": results
            }


scan_manager = ScanManager()