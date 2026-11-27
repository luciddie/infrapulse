from datetime import datetime

from sqlalchemy import (
    String,
    Integer,
    Boolean,
    Float,
    DateTime,
    ForeignKey,
    CheckConstraint,
    func
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Service(Base):
    __tablename__ = "services"

    __table_args__ = (
        CheckConstraint(
            "protocol IN ('tcp', 'http')",
            name="ck_service_protocol"
        ),
        CheckConstraint(
            "port IS NULL OR port BETWEEN 1 AND 65535",
            name="ck_service_port"
        ),
        CheckConstraint(
            "timeout_seconds > 0 AND timeout_seconds <= 10",
            name="ck_service_timeout"
        ),
        CheckConstraint(
            "expected_status BETWEEN 100 AND 599",
            name="ck_service_http_status"
        ),
        CheckConstraint(
            "(protocol = 'tcp' AND port IS NOT NULL AND url IS NULL) "
            "OR (protocol = 'http' AND url IS NOT NULL AND port IS NULL)",
            name="ck_service_target"
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

    name: Mapped[str] = mapped_column(
        String(100)
    )

    protocol: Mapped[str] = mapped_column(
        String(10)
    )

    port: Mapped[int | None] = mapped_column(
        Integer
    )

    url: Mapped[str | None] = mapped_column(
        String(2048)
    )

    expected_status: Mapped[int] = mapped_column(
        Integer,
        default=200
    )

    timeout_seconds: Mapped[float] = mapped_column(
        Float,
        default=3.0
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="unknown"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
