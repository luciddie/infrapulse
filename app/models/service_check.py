from datetime import datetime

from sqlalchemy import (
    String,
    Integer,
    Float,
    Text,
    DateTime,
    ForeignKey,
    func
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ServiceCheck(Base):
    __tablename__ = "service_checks"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"),
        index=True
    )

    status: Mapped[str] = mapped_column(
        String(20)
    )

    status_code: Mapped[int | None] = mapped_column(
        Integer
    )

    latency_ms: Mapped[float | None] = mapped_column(
        Float
    )

    error: Mapped[str | None] = mapped_column(
        Text
    )

    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )
