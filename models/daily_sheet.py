from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin, enum_type
from models.enums import DailyRoomStatus, SessionOutcome


class DailySheet(Base, TimestampMixin):
    """One day's housekeeping task sheet, uploaded as PDF by the HK supervisor."""

    __tablename__ = "daily_sheets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False, index=True)
    source_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uploaded_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    upload_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    uploaded_by = relationship("User", lazy="joined")
    rooms = relationship("DailySheetRoom", back_populates="sheet", lazy="selectin",
                         order_by="(DailySheetRoom.sheet_no, DailySheetRoom.room_number)",
                         cascade="all, delete-orphan")


class DailySheetRoom(Base, TimestampMixin):
    """A room on a day's task sheet, its assignment to a room attendant and its progress."""

    __tablename__ = "daily_sheet_rooms"
    __table_args__ = (UniqueConstraint("sheet_id", "room_number", name="uq_daily_sheet_room"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("daily_sheets.id", ondelete="CASCADE"), nullable=False, index=True)
    room_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rooms.id"), nullable=True, index=True)
    room_number: Mapped[str] = mapped_column(String(20), nullable=False)
    sheet_no: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    room_type_code: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    hk_status: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    fo_status: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    reservation_status: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    arrival_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    departure_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    arrival_today: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[DailyRoomStatus] = mapped_column(enum_type(DailyRoomStatus), default=DailyRoomStatus.PENDING,
                                                    nullable=False, index=True)
    outcome: Mapped[Optional[SessionOutcome]] = mapped_column(enum_type(SessionOutcome), nullable=True)
    assigned_ra_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    on_latest_upload: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sheet = relationship("DailySheet", back_populates="rooms")
    room = relationship("Room", lazy="joined")
    assigned_ra = relationship("User", lazy="joined")
    sessions = relationship("InspectionSession", primaryjoin="DailySheetRoom.id == foreign(InspectionSession.daily_room_id)",
                            order_by="InspectionSession.id", lazy="selectin", viewonly=True)
