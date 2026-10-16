from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin, enum_type
from models.enums import OccupancyStatus, OperationalStatus


class RoomType(Base, TimestampMixin):
    __tablename__ = "room_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Room(Base, TimestampMixin):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    floor: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    room_type_id: Mapped[int] = mapped_column(ForeignKey("room_types.id"), nullable=False)
    occupancy_status: Mapped[OccupancyStatus] = mapped_column(
        enum_type(OccupancyStatus), default=OccupancyStatus.VACANT, nullable=False, index=True
    )
    operational_status: Mapped[OperationalStatus] = mapped_column(
        enum_type(OperationalStatus), default=OperationalStatus.READY_FOR_GUEST, nullable=False, index=True
    )
    active_ticket_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("turnover_tickets.id", use_alter=True, name="fk_rooms_active_ticket"), nullable=True
    )
    assigned_housekeeper_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    assigned_engineer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    last_inspection_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_ready_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    room_type = relationship("RoomType", lazy="joined")
    active_ticket = relationship("TurnoverTicket", foreign_keys=[active_ticket_id], lazy="joined", post_update=True)
    assigned_housekeeper = relationship("User", foreign_keys=[assigned_housekeeper_id], lazy="joined")
    assigned_engineer = relationship("User", foreign_keys=[assigned_engineer_id], lazy="joined")

    open_repairs = relationship(
        "RepairRequest",
        primaryjoin="and_(Room.id == foreign(RepairRequest.room_id), "
                    "RepairRequest.status.in_(['NEW', 'ASSIGNED', 'IN_PROGRESS', 'REOPENED']))",
        viewonly=True,
        lazy="selectin",
    )

    __mapper_args__ = {"version_id_col": version}
