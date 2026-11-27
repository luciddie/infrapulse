import logging

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock, Thread

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models.device import Device
from app.models.service import Service
from app.services.health_checker import check_device
from app.services.service_checker import check_service


logger = logging.getLogger("infrapulse.scheduler")


class MonitoringScheduler:

    def __init__(self):
        self.stop_event = Event()
        self.lock = Lock()
        self.thread = None

    def safe_check(self, device_id: int):

        if self.stop_event.is_set():
            return

        try:
            check_device(device_id)

        except Exception:
            logger.exception(
                "Device check failed: %s",
                device_id
            )

    def safe_service_check(self, service_id: int):

        if self.stop_event.is_set():
            return

        try:
            check_service(service_id)

        except Exception:
            logger.exception(
                "Service check failed: %s",
                service_id
            )

    def run_cycle(self):

        with SessionLocal() as db:

            device_ids = list(
                db.scalars(
                    select(Device.id)
                    .order_by(Device.id)
                ).all()
            )

            service_ids = list(
                db.scalars(
                    select(Service.id)
                    .where(Service.enabled.is_(True))
                    .order_by(Service.id)
                ).all()
            )

        logger.info(
            "Monitoring cycle: %s devices, %s services",
            len(device_ids),
            len(service_ids)
        )

        with ThreadPoolExecutor(
            max_workers=settings.monitoring_workers
        ) as executor:

            futures = []

            for device_id in device_ids:
                futures.append(
                    executor.submit(
                        self.safe_check,
                        device_id
                    )
                )

            for service_id in service_ids:
                futures.append(
                    executor.submit(
                        self.safe_service_check,
                        service_id
                    )
                )

            for future in futures:
                future.result()

        logger.info("Monitoring cycle completed")

    def _loop(self):

        while not self.stop_event.is_set():

            try:
                self.run_cycle()

            except Exception:
                logger.exception(
                    "Monitoring cycle failed"
                )

            self.stop_event.wait(
                settings.monitoring_interval
            )

    def start(self):

        with self.lock:

            if self.thread and self.thread.is_alive():
                return

            if settings.monitoring_interval < 1:
                raise ValueError(
                    "Invalid monitoring interval"
                )

            if not 1 <= settings.monitoring_workers <= 16:
                raise ValueError(
                    "Invalid monitoring workers"
                )

            self.stop_event.clear()

            self.thread = Thread(
                target=self._loop,
                name="infrapulse-monitoring",
                daemon=True
            )

            self.thread.start()

            logger.info("Monitoring scheduler started")

    def stop(self):

        with self.lock:

            self.stop_event.set()

            if self.thread:
                self.thread.join()
                self.thread = None

            logger.info("Monitoring scheduler stopped")


scheduler = MonitoringScheduler()