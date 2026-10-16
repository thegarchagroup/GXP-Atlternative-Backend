from typing import Optional

from pydantic import BaseModel, Field

from models.enums import OccupancyStatus, OperationalStatus
from schemas.common import ORMModel, UserBrief, UTCDateTime, user_brief


class RoomTypeOut(ORMModel):
    id: int
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    is_active: bool


class RoomTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    category: Optional[str] = Field(default=None, max_length=80)
    description: Optional[str] = None
    is_active: bool = True


class RoomTypeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    category: Optional[str] = Field(default=None, max_length=80)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class RoomOut(BaseModel):
    id: int
    room_number: str
    floor: int
    room_type: RoomTypeOut
    occupancy_status: OccupancyStatus
    operational_status: OperationalStatus
    active_ticket_id: Optional[int] = None
    active_ticket_number: Optional[str] = None
    active_ticket_created_at: Optional[UTCDateTime] = None
    assigned_housekeeper: Optional[UserBrief] = None
    assigned_engineer: Optional[UserBrief] = None
    last_inspection_at: Optional[UTCDateTime] = None
    last_ready_at: Optional[UTCDateTime] = None
    notes: Optional[str] = None
    is_active: bool
    open_repairs: int = 0
    created_at: UTCDateTime
    updated_at: UTCDateTime


class RoomCreate(BaseModel):
    room_number: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9-]+$")
    floor: int = Field(ge=-5, le=300)
    room_type_id: int
    occupancy_status: OccupancyStatus = OccupancyStatus.VACANT
    operational_status: OperationalStatus = OperationalStatus.READY_FOR_GUEST
    notes: Optional[str] = None


class RoomUpdate(BaseModel):
    room_number: Optional[str] = Field(default=None, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9-]+$")
    floor: Optional[int] = Field(default=None, ge=-5, le=300)
    room_type_id: Optional[int] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class RoomStatusOverride(BaseModel):
    """Exceptional admin change, always audited. Ready for Guest is only possible
    when no turnover ticket is open (use the release workflow otherwise)."""
    operational_status: OperationalStatus
    reason: str = Field(min_length=3, max_length=1000)


class RoomOccupancyUpdate(BaseModel):
    occupancy_status: OccupancyStatus
    reason: Optional[str] = Field(default=None, max_length=1000)


def room_out(room) -> RoomOut:
    t = room.active_ticket
    return RoomOut(
        id=room.id,
        room_number=room.room_number,
        floor=room.floor,
        room_type=RoomTypeOut.model_validate(room.room_type),
        occupancy_status=room.occupancy_status,
        operational_status=room.operational_status,
        active_ticket_id=room.active_ticket_id,
        active_ticket_number=t.ticket_number if t else None,
        active_ticket_created_at=t.created_at if t else None,
        assigned_housekeeper=user_brief(room.assigned_housekeeper),
        assigned_engineer=user_brief(room.assigned_engineer),
        last_inspection_at=room.last_inspection_at,
        last_ready_at=room.last_ready_at,
        notes=room.notes,
        is_active=room.is_active,
        open_repairs=len(room.open_repairs),
        created_at=room.created_at,
        updated_at=room.updated_at,
    )
