from fastapi import FastAPI, HTTPException
from app.api.network import router as network_router
from app.api.devices import router as devices_router
from app.api.history import router as history_router
from app.api.health import router as health_router
from app.api.incidents import router as incidents_router
from app.api.services import router as services_router
from contextlib import asynccontextmanager
from app.api.service_incidents import router as service_incidents_router
from app.api.metrics import router as metrics_router

from app.config import settings
from app.database import check_database
from app.metrics import MONITORING_ENABLED, MONITORING_INTERVAL_SECONDS
from app.services.scheduler import scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    MONITORING_ENABLED.set(1 if settings.monitoring_enabled else 0)
    MONITORING_INTERVAL_SECONDS.set(settings.monitoring_interval)
    if settings.monitoring_enabled:
        scheduler.start()

    try:
        yield
    finally:
        scheduler.stop()
        MONITORING_ENABLED.set(0)

app = FastAPI(
    title="InfraPulse",
    version="0.1.0",
    lifespan=lifespan
)

app.include_router(network_router)
app.include_router(devices_router)
app.include_router(history_router)
app.include_router(health_router)
app.include_router(incidents_router)
app.include_router(services_router)
app.include_router(service_incidents_router)
app.include_router(metrics_router)

@app.get("/")
def root():
    return {
        "name": "InfraPulse",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.get("/ready")
def ready():
    try:
        is_ready = check_database()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database is not ready"
        )

    if not is_ready:
        raise HTTPException(
            status_code=503,
            detail="Database is not ready"
        )

    return {
        "status": "ready",
        "database": "connected"
    }
