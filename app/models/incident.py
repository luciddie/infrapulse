from datetime import datetime

from sqlalchemy import (
    String,
    DateTime,
    ForeignKey,
    Index,
    text,
    func
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Incident(Base):
    __tablename__ = "incidents"

    __table_args__ = (
        Index(
            "uq_incidents_open_device",
            "device_id",
            unique=True,
            postgresql_where=text("status = 'open'")
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        index=True
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="open",
        index=True
    )

    reason: Mapped[str] = mapped_column(
        String(255)
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
