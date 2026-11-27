from datetime import datetime

from sqlalchemy import (
    String,
    Float,
    ForeignKey,
    DateTime,
    Text,
    func
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HealthCheck(Base):
    __tablename__ = "health_checks"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        index=True
    )

    status: Mapped[str] = mapped_column(
        String(20)
    )

    latency_ms: Mapped[float | None] = mapped_column(
        Float
    )

    latency_upper_bound_ms: Mapped[float | None] = mapped_column(
        Float
    )

    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    error: Mapped[str | None] = mapped_column(
        Text
    )
