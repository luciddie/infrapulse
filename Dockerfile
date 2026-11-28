# syntax=docker/dockerfile:1

FROM python:3.14-slim@sha256:080b4f1282edb604b21e61dfca35d1d215ed6cd1c17de27ccfc34e6fadc4ee49 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /build

RUN python -m venv /opt/venv

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    && python -m pip check \
    && rm -rf /opt/venv/lib/python*/site-packages/pip* /opt/venv/bin/pip*


FROM python:3.14-slim@sha256:080b4f1282edb604b21e61dfca35d1d215ed6cd1c17de27ccfc34e6fadc4ee49 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        iputils-ping \
        iproute2 \
        ca-certificates \
    && apt-get install -y --no-install-recommends --only-upgrade \
        libzstd1 \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/python*/site-packages/pip* /usr/local/bin/pip*

RUN groupadd --gid 10001 --system infrapulse \
    && useradd --uid 10001 --gid 10001 --system --no-create-home --shell /usr/sbin/nologin infrapulse

WORKDIR /app

COPY --from=builder --chown=root:root /opt/venv /opt/venv
COPY --chown=root:root alembic.ini ./alembic.ini
COPY --chown=root:root migrations/ ./migrations/
COPY --chown=root:root app/ ./app/

USER 10001:10001

EXPOSE 8000

# Lightweight HTTP liveness check against /health (verifies app responsiveness only)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
