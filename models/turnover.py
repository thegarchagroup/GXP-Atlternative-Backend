from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin, enum_type, utcnow
from models.enums import Department, Priority, TicketStatus


class TurnoverTicket(Base, TimestampMixin):
    __tablename__ = "turnover_tickets"
    __table_args__ = (
        # One active ticket per room. Closed/cancelled tickets and admin-approved
        # exceptions store NULL here, which MySQL allows to repeat.
        UniqueConstraint("active_room_key", name="uq_turnover_active_room"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_number: Mapped[Optional[str]] = mapped_column(String(32), unique=True, nullable=True, index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False, index=True)
    status: Mapped[TicketStatus] = mapped_column(enum_type(TicketStatus), nullable=False, index=True)
    priority: Mapped[Priority] = mapped_column(enum_type(Priority), default=Priority.NORMAL, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    active_room_key: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_exception: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exception_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    needs_reclean: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    assigned_housekeeper_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    housekeeping_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    housekeeping_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    released_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    room = relationship("Room", foreign_keys=[room_id], lazy="joined")
    assigned_housekeeper = relationship("User", foreign_keys=[assigned_housekeeper_id], lazy="joined")
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="joined")
    released_by = relationship("User", foreign_keys=[released_by_id], lazy="joined")
    repairs = relationship("RepairRequest", back_populates="ticket", order_by="RepairRequest.id", lazy="selectin")
    sessions = relationship("InspectionSession", back_populates="ticket", order_by="InspectionSession.id", lazy="selectin")

    __mapper_args__ = {"version_id_col": version}


class TicketAssignment(Base):
    __tablename__ = "ticket_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[Optional[int]] = mapped_column(ForeignKey("turnover_tickets.id"), nullable=True, index=True)
    repair_id: Mapped[Optional[int]] = mapped_column(ForeignKey("repair_requests.id"), nullable=True, index=True)
    department: Mapped[Department] = mapped_column(enum_type(Department), nullable=False)
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    previous_assignee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    assignee = relationship("User", foreign_keys=[assignee_id], lazy="joined")
    previous_assignee = relationship("User", foreign_keys=[previous_assignee_id], lazy="joined")
    assigned_by = relationship("User", foreign_keys=[assigned_by_id], lazy="joined")
