from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import String, Integer, DateTime, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScanRecord(Base):
    __tablename__ = "scans"

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4
    )

    network: Mapped[str] = mapped_column(
        String(50)
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        index=True
    )

    scanned_hosts: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    online_devices: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    error: Mapped[str | None] = mapped_column(
        Text
    )
