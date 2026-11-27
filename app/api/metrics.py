import logging

from fastapi import APIRouter, Response

from prometheus_client import (
    generate_latest,
    CONTENT_TYPE_LATEST
)

from app.services.metrics_collector import (
    collect_database_metrics
)


logger = logging.getLogger("infrapulse.metrics")

router = APIRouter(tags=["Metrics"])


@router.get("/metrics", include_in_schema=False)
def get_metrics():

    try:
        collect_database_metrics()

    except Exception as exc:
        logger.warning(
            "Metrics collection failed: %s",
            type(exc).__name__
        )

        return Response(
            content="Database metrics unavailable",
            status_code=503,
            media_type="text/plain"
        )

    return Response(
        content=generate_latest(),
        headers={
            "Content-Type": CONTENT_TYPE_LATEST
        }
    )
