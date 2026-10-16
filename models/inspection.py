from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin, enum_type, utcnow
from models.enums import ChecklistType, ItemResult, SessionKind, SessionOutcome, SessionStatus


class InspectionSession(Base, TimestampMixin):
    """One pass of a checklist. Items are copied (snapshotted) from the master
    templates when the session starts, so later template edits never change history."""

    __tablename__ = "inspection_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[Optional[int]] = mapped_column(ForeignKey("turnover_tickets.id"), nullable=True, index=True)
    repair_id: Mapped[Optional[int]] = mapped_column(ForeignKey("repair_requests.id"), nullable=True, index=True)
    kind: Mapped[SessionKind] = mapped_column(enum_type(SessionKind), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_reclean: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[SessionStatus] = mapped_column(enum_type(SessionStatus), nullable=False)
    outcome: Mapped[Optional[SessionOutcome]] = mapped_column(enum_type(SessionOutcome), nullable=True)
    inspector_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    submitted_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    ticket = relationship("TurnoverTicket", back_populates="sessions")
    inspector = relationship("User", foreign_keys=[inspector_id], lazy="joined")
    results = relationship(
        "InspectionResult", back_populates="session",
        order_by="(InspectionResult.checklist_type, InspectionResult.display_order, InspectionResult.id)",
        lazy="selectin",
    )


class InspectionResult(Base):
    __tablename__ = "inspection_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("inspection_sessions.id"), nullable=False, index=True)
    template_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("checklist_template_items.id"), nullable=True)
    checklist_type: Mapped[ChecklistType] = mapped_column(enum_type(ChecklistType), nullable=False)
    # Snapshot of the template item at the time the session started
    item_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allow_not_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reference_instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Outcome
    result: Mapped[ItemResult] = mapped_column(enum_type(ItemResult), default=ItemResult.PENDING, nullable=False)
    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    inspector_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    inspected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    session = relationship("InspectionSession", back_populates="results")
    inspector = relationship("User", foreign_keys=[inspector_id], lazy="joined")
    attachments = relationship("Attachment", back_populates="inspection_result", lazy="selectin")


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    ticket_id: Mapped[Optional[int]] = mapped_column(ForeignKey("turnover_tickets.id"), nullable=True, index=True)
    repair_id: Mapped[Optional[int]] = mapped_column(ForeignKey("repair_requests.id"), nullable=True, index=True)
    inspection_result_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inspection_results.id"), nullable=True, index=True)
    caption: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    inspection_result = relationship("InspectionResult", back_populates="attachments")
    uploaded_by = relationship("User", lazy="joined")
