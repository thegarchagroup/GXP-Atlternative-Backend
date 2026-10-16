from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, utcnow


class ActivityLog(Base):
    """Append-only audit trail for workflow and administrative actions."""

    __tablename__ = "ticket_activity_logs"
    __table_args__ = (Index("ix_activity_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ticket_id: Mapped[Optional[int]] = mapped_column(ForeignKey("turnover_tickets.id"), nullable=True, index=True)
    repair_id: Mapped[Optional[int]] = mapped_column(ForeignKey("repair_requests.id"), nullable=True, index=True)
    room_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rooms.id"), nullable=True, index=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    from_status: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    to_status: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    actor = relationship("User", lazy="joined")
