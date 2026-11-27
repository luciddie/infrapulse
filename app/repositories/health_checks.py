from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.health_check import HealthCheck


def create_health_check(
    db: Session,
    device_id: int,
    result: dict
) -> HealthCheck:

    check = HealthCheck(
        device_id=device_id,
        status=result["status"],
        latency_ms=result.get("latency_ms"),
        latency_upper_bound_ms=result.get(
            "latency_upper_bound_ms"
        ),
        error=result.get("error")
    )

    db.add(check)
    db.flush()

    return check


def list_health_checks(
    db: Session,
    device_id: int,
    limit: int = 100,
    offset: int = 0
) -> list[HealthCheck]:

    stmt = (
        select(HealthCheck)
        .where(HealthCheck.device_id == device_id)
        .order_by(
            HealthCheck.checked_at.desc(),
            HealthCheck.id.desc()
        )
        .limit(limit)
        .offset(offset)
    )

    return list(db.scalars(stmt).all())


def get_latest_health_check(
    db: Session,
    device_id: int
) -> HealthCheck | None:

    stmt = (
        select(HealthCheck)
        .where(HealthCheck.device_id == device_id)
        .order_by(
            HealthCheck.checked_at.desc(),
            HealthCheck.id.desc()
        )
        .limit(1)
    )

    return db.scalar(stmt)
