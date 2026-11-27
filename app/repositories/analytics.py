from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func, case
from sqlalchemy.orm import Session

from app.models.health_check import HealthCheck


def get_device_analytics(
    db: Session,
    device_id: int,
    hours: int = 24
) -> dict:

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)

    stmt = select(
        func.count(HealthCheck.id).label("total"),

        func.count(case(
            (HealthCheck.status == "online", 1)
        )).label("online"),

        func.count(case(
            (HealthCheck.status == "no_response", 1)
        )).label("no_response"),

        func.count(case(
            (HealthCheck.status == "unknown", 1)
        )).label("unknown"),

        func.avg(HealthCheck.latency_ms).filter(
            HealthCheck.status == "online"
        ).label("avg_latency"),

        func.min(HealthCheck.latency_ms).filter(
            HealthCheck.status == "online"
        ).label("min_latency"),

        func.max(HealthCheck.latency_ms).filter(
            HealthCheck.status == "online"
        ).label("max_latency"),

        func.count(HealthCheck.latency_ms).filter(
            HealthCheck.status == "online"
        ).label("latency_samples"),

        func.max(HealthCheck.checked_at).label(
            "last_check"
        )

    ).where(
        HealthCheck.device_id == device_id,
        HealthCheck.checked_at >= since,
        HealthCheck.checked_at <= now
    )

    row = db.execute(stmt).one()

    total = row.total
    online = row.online
    no_response = row.no_response
    unknown = row.unknown

    valid_checks = online + no_response

    uptime = (
        round(online / valid_checks * 100, 2)
        if valid_checks else None
    )

    def rounded(value):
        return round(float(value), 2) if value is not None else None

    return {
        "device_id": device_id,
        "period_hours": hours,
        "period_start": since,
        "period_end": now,
        "total_checks": total,
        "online_checks": online,
        "no_response_checks": no_response,
        "unknown_checks": unknown,
        "uptime_percent": uptime,
        "avg_latency_ms": rounded(row.avg_latency),
        "min_latency_ms": rounded(row.min_latency),
        "max_latency_ms": rounded(row.max_latency),
        "latency_samples": row.latency_samples,
        "last_check": row.last_check
    }