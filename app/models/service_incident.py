from datetime import datetime

from sqlalchemy import (
    String,
    DateTime,
    ForeignKey,
    Index,
    CheckConstraint,
    func,
    text
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ServiceIncident(Base):

    __tablename__ = "service_incidents"

    __table_args__ = (
        Index(
            "uq_service_incidents_open_service",
            "service_id",
            unique=True,
            postgresql_where=text("status = 'open'")
        ),
        CheckConstraint(
            "status IN ('open', 'resolved')",
            name="ck_service_incident_status"
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    service_id: Mapped[int] = mapped_column(
        ForeignKey(
            "services.id",
            ondelete="CASCADE"
        ),
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
