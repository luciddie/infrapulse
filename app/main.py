from fastapi import FastAPI
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
from app.services.scheduler import scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.monitoring_enabled:
        scheduler.start()

    try:
        yield
    finally:
        scheduler.stop()

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
