from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func, case
from sqlalchemy.orm import Session

from app.models.service_check import ServiceCheck


def get_service_analytics(
    db: Session,
    service_id: int,
    hours: int = 24
) -> dict:

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)

    success = ServiceCheck.status.in_(
        ["open", "healthy"]
    )

    failure = ServiceCheck.status.in_(
        [
            "closed",
            "unhealthy",
            "unreachable",
            "timeout"
        ]
    )

    stmt = select(
        func.count(ServiceCheck.id).label("total"),

        func.sum(
            case((success, 1), else_=0)
        ).label("successful"),

        func.sum(
            case((failure, 1), else_=0)
        ).label("failed"),

        func.sum(
            case(
                (ServiceCheck.status == "timeout", 1),
                else_=0
            )
        ).label("timeouts"),

        func.avg(
            case(
                (success, ServiceCheck.latency_ms),
                else_=None
            )
        ).label("avg_latency"),

        func.min(
            case(
                (success, ServiceCheck.latency_ms),
                else_=None
            )
        ).label("min_latency"),

        func.max(
            case(
                (success, ServiceCheck.latency_ms),
                else_=None
            )
        ).label("max_latency"),

        func.max(
            ServiceCheck.checked_at
        ).label("last_check")

    ).where(
        ServiceCheck.service_id == service_id,
        ServiceCheck.checked_at >= since,
        ServiceCheck.checked_at <= now
    )

    row = db.execute(stmt).one()

    total = row.total or 0
    successful = row.successful or 0
    failed = row.failed or 0
    unknown = total - successful - failed

    valid = successful + failed

    availability = (
        round(successful / valid * 100, 2)
        if valid else None
    )

    def rounded(value):
        return (
            round(float(value), 2)
            if value is not None else None
        )

    return {
        "service_id": service_id,
        "period_hours": hours,
        "period_start": since.isoformat(),
        "period_end": now.isoformat(),

        "total_checks": total,
        "successful_checks": successful,
        "failed_checks": failed,
        "unknown_checks": unknown,
        "timeout_checks": row.timeouts or 0,

        "availability_percent": availability,

        "avg_latency_ms": rounded(row.avg_latency),
        "min_latency_ms": rounded(row.min_latency),
        "max_latency_ms": rounded(row.max_latency),

        "last_check": (
            row.last_check.isoformat()
            if row.last_check else None
        )
    }
