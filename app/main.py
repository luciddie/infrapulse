from fastapi import FastAPI
from app.api.network import router as network_router


app = FastAPI(
    title="InfraPulse",
    description="Network discovery and infrastructure monitoring platform",
    version="0.1.0"
)


app.include_router(network_router)


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
