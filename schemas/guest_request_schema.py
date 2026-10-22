from typing import Optional

from pydantic import BaseModel, Field

from models.enums import Priority, RequestStatus
from schemas.common import UserBrief, UTCDateTime, user_brief


class GuestRequestCreate(BaseModel):
    room_id: int
    description: str = Field(min_length=2, max_length=2000)
    priority: Priority = Priority.NORMAL


class GuestRequestAssign(BaseModel):
    ra_id: int


class GuestRequestDone(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


class GuestRequestCancel(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)


class GuestRequestOut(BaseModel):
    id: int
    request_number: Optional[str]
    room_id: int
    room_number: str
    floor: int
    description: str
    priority: Priority
    status: RequestStatus
    created_by: Optional[UserBrief] = None
    assigned_ra: Optional[UserBrief] = None
    assigned_by: Optional[UserBrief] = None
    created_at: UTCDateTime
    assigned_at: Optional[UTCDateTime] = None
    started_at: Optional[UTCDateTime] = None
    completed_at: Optional[UTCDateTime] = None
    completion_note: Optional[str] = None
    cancelled_at: Optional[UTCDateTime] = None
    cancel_reason: Optional[str] = None
    minutes_to_complete: Optional[float] = None


def request_out(r) -> GuestRequestOut:
    return GuestRequestOut(
        id=r.id, request_number=r.request_number, room_id=r.room_id, room_number=r.room.room_number, floor=r.room.floor,
        description=r.description, priority=r.priority, status=r.status, created_by=user_brief(r.created_by),
        assigned_ra=user_brief(r.assigned_ra), assigned_by=user_brief(r.assigned_by), created_at=r.created_at,
        assigned_at=r.assigned_at, started_at=r.started_at, completed_at=r.completed_at, completion_note=r.completion_note,
        cancelled_at=r.cancelled_at, cancel_reason=r.cancel_reason,
        minutes_to_complete=round((r.completed_at - r.created_at).total_seconds() / 60, 1) if r.completed_at else None,
    )
