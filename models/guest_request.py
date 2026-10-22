from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin, enum_type
from models.enums import Priority, RequestStatus


class GuestRequest(Base, TimestampMixin):
    """A free-text request from the front desk for a room (e.g. "water bottle"), done by a room attendant."""

    __tablename__ = "guest_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_number: Mapped[Optional[str]] = mapped_column(String(32), unique=True, nullable=True, index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[Priority] = mapped_column(enum_type(Priority), default=Priority.NORMAL, nullable=False)
    status: Mapped[RequestStatus] = mapped_column(enum_type(RequestStatus), default=RequestStatus.NEW, nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_ra_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    assigned_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completion_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    room = relationship("Room", lazy="joined")
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="joined")
    assigned_ra = relationship("User", foreign_keys=[assigned_ra_id], lazy="joined")
    assigned_by = relationship("User", foreign_keys=[assigned_by_id], lazy="joined")
