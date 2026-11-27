from fastapi import FastAPI

app = FastAPI(
    title="InfraPulse",
    description="Network discovery and infrastructure monitoring platform",
    version="0.1.0"
)


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