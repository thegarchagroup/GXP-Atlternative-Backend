from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin, enum_type
from models.enums import PendingReason, Priority, RepairStatus


class RepairRequest(Base, TimestampMixin):
    __tablename__ = "repair_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repair_number: Mapped[Optional[str]] = mapped_column(String(32), unique=True, nullable=True, index=True)
    # NULL for a repair raised directly by the front desk on a room with no turnover in progress
    ticket_id: Mapped[Optional[int]] = mapped_column(ForeignKey("turnover_tickets.id"), nullable=True, index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False, index=True)
    source_session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("inspection_sessions.id", use_alter=True, name="fk_repair_source_session"), nullable=True)
    status: Mapped[RepairStatus] = mapped_column(enum_type(RepairStatus), nullable=False, index=True)
    priority: Mapped[Priority] = mapped_column(enum_type(Priority), default=Priority.NORMAL, nullable=False)
    reported_defect: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_engineer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    diagnosis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    repair_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # True when the repair took a vacant, ready room off sale until it is completed
    blocks_room: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_recleaning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_reopen_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # "not doable now"
    pending_reason: Mapped[Optional[PendingReason]] = mapped_column(enum_type(PendingReason), nullable=True)
    pending_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expected_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    pending_since: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    room_sellable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    escalation_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    ticket = relationship("TurnoverTicket", back_populates="repairs", lazy="joined")
    room = relationship("Room", lazy="joined")
    assigned_engineer = relationship("User", foreign_keys=[assigned_engineer_id], lazy="joined")
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="joined")
    sessions = relationship(
        "InspectionSession",
        primaryjoin="RepairRequest.id == InspectionSession.repair_id",
        order_by="InspectionSession.id",
        lazy="selectin",
        viewonly=True,
    )

    @property
    def origin(self) -> str:
        """HOUSEKEEPING when raised by a failed inspection, FRONT_DESK when raised directly."""
        return "HOUSEKEEPING" if self.source_session_id else "FRONT_DESK"

    __mapper_args__ = {"version_id_col": version}
