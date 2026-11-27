from sqlalchemy import select, func

from app.database import SessionLocal

from app.models.device import Device
from app.models.service import Service
from app.models.incident import Incident
from app.models.service_incident import ServiceIncident

from app.metrics import (
    DEVICES_TOTAL,
    SERVICES_TOTAL,
    OPEN_INCIDENTS
)


def collect_database_metrics():

    with SessionLocal() as db:

        devices = db.scalar(
            select(func.count(Device.id))
        ) or 0

        services = db.scalar(
            select(func.count(Service.id))
        ) or 0

        device_incidents = db.scalar(
            select(func.count(Incident.id))
            .where(Incident.status == "open")
        ) or 0

        service_incidents = db.scalar(
            select(func.count(ServiceIncident.id))
            .where(ServiceIncident.status == "open")
        ) or 0

    DEVICES_TOTAL.set(devices)

    SERVICES_TOTAL.set(services)

    OPEN_INCIDENTS.labels(
        type="device"
    ).set(device_incidents)

    OPEN_INCIDENTS.labels(
        type="service"
    ).set(service_incidents)
