from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    String,
    Float,
    ForeignKey,
    DateTime,
    UniqueConstraint,
    Uuid,
    func
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScanResult(Base):
    __tablename__ = "scan_results"

    __table_args__ = (
        UniqueConstraint(
            "scan_id",
            "ip_address",
            name="uq_scan_result_ip"
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    scan_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("scans.id", ondelete="CASCADE"),
        index=True
    )

    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"),
        index=True
    )

    ip_address: Mapped[str] = mapped_column(
        String(45)
    )

    mac_address: Mapped[str | None] = mapped_column(
        String(17)
    )

    hostname: Mapped[str | None] = mapped_column(
        String(255)
    )

    vendor: Mapped[str | None] = mapped_column(
        String(255)
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

    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
