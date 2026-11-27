from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.models.device import Device


def get_device_by_ip(
    db: Session,
    ip_address: str
) -> Device | None:
    return db.scalar(
        select(Device).where(
            Device.ip_address == ip_address
        )
    )


def upsert_device(
    db: Session,
    data: dict
) -> Device:
    now = datetime.now(timezone.utc)

    stmt = insert(Device).values(
        ip_address=data["ip"],
        mac_address=data.get("mac"),
        hostname=data.get("hostname"),
        vendor=data.get("vendor"),
        status="online",
        first_seen=now,
        last_seen=now
    )

    stmt = stmt.on_conflict_do_update(
        index_elements=[Device.ip_address],
        set_={
            "mac_address": func.coalesce(
                stmt.excluded.mac_address,
                Device.mac_address
            ),
            "hostname": func.coalesce(
                stmt.excluded.hostname,
                Device.hostname
            ),
            "vendor": func.coalesce(
                stmt.excluded.vendor,
                Device.vendor
            ),
            "status": "online",
            "last_seen": now,
            "updated_at": now
        }
    ).returning(Device)

    return db.scalars(
        stmt,
        execution_options={"populate_existing": True}
    ).one()


def list_devices(
    db: Session,
    limit: int = 100,
    offset: int = 0
) -> list[Device]:
    stmt = (
        select(Device)
        .order_by(Device.id)
        .limit(limit)
        .offset(offset)
    )

    return list(db.scalars(stmt).all())


def count_devices(db: Session) -> int:
    stmt = select(func.count(Device.id))

    return db.scalar(stmt) or 0
