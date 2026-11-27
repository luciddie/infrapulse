from uuid import uuid4
from datetime import datetime, timezone
from threading import Lock
from concurrent.futures import ThreadPoolExecutor

from app.services.scanner import scan_network


class ScanManager:

    def __init__(self):
        self.scans = {}
        self.lock = Lock()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.max_history = 10

    def start_scan(self, **params):
        with self.lock:
            active = any(
                scan["status"] in ("pending", "running")
                for scan in self.scans.values()
            )

            if active:
                raise RuntimeError("Another scan is already running")

            while len(self.scans) >= self.max_history:
                oldest = next(iter(self.scans))
                del self.scans[oldest]

            scan_id = str(uuid4())

            self.scans[scan_id] = {
                "id": scan_id,
                "status": "pending",
                "network": params["cidr"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "results": None,
                "error": None
            }

            self.executor.submit(
                self._run_scan,
                scan_id,
                params
            )

        return scan_id

    def _run_scan(self, scan_id, params):
        with self.lock:
            self.scans[scan_id]["status"] = "running"

        try:
            results = scan_network(**params)

            with self.lock:
                self.scans[scan_id].update({
                    "status": "completed",
                    "results": results,
                    "finished_at": datetime.now(
                        timezone.utc
                    ).isoformat()
                })

        except Exception as error:
            with self.lock:
                self.scans[scan_id].update({
                    "status": "failed",
                    "error": str(error),
                    "finished_at": datetime.now(
                        timezone.utc
                    ).isoformat()
                })

    def get_scan(self, scan_id):
        with self.lock:
            scan = self.scans.get(scan_id)
            return scan.copy() if scan else None


scan_manager = ScanManager()
