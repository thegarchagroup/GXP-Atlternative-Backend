from typing import Optional

from pydantic import BaseModel, Field

from models.enums import Priority, RepairStatus
from schemas.common import UserBrief, UTCDateTime, user_brief
from schemas.inspection_schema import InspectionResultOut, InspectionSessionOut, Progress, compute_progress


class RepairOut(BaseModel):
    id: int
    repair_number: Optional[str]
    ticket_id: Optional[int] = None
    ticket_number: Optional[str] = None
    ticket_status: str = ""
    origin: str = "HOUSEKEEPING"
    blocks_room: bool = False
    room_id: int
    room_number: str
    floor: int
    room_occupancy: str = ""
    room_status: str = ""
    status: RepairStatus
    priority: Priority
    reported_defect: str
    assigned_engineer: Optional[UserBrief] = None
    created_by: Optional[UserBrief] = None
    diagnosis: Optional[str] = None
    repair_notes: Optional[str] = None
    requires_recleaning: bool
    reopen_count: int
    last_reopen_reason: Optional[str] = None
    started_at: Optional[UTCDateTime] = None
    completed_at: Optional[UTCDateTime] = None
    created_at: UTCDateTime
    updated_at: UTCDateTime
    progress: Optional[Progress] = None


class RepairDetailOut(RepairOut):
    failed_items: list[InspectionResultOut] = []
    housekeeping_notes: Optional[str] = None
    sessions: list[InspectionSessionOut] = []
    room_repair_history: list[RepairOut] = []


class DirectRepairCreate(BaseModel):
    room_id: int
    reported_defect: str = Field(min_length=3, max_length=5000)
    priority: Priority = Priority.NORMAL
    engineer_id: Optional[int] = None


class RepairAssignRequest(BaseModel):
    engineer_id: int
    reason: Optional[str] = Field(default=None, max_length=1000)


class RepairCompleteRequest(BaseModel):
    requires_recleaning: bool = False
    diagnosis: Optional[str] = Field(default=None, max_length=5000)
    repair_notes: Optional[str] = Field(default=None, max_length=5000)


class RepairReopenRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


def repair_out(r) -> RepairOut:
    current = r.sessions[-1] if r.sessions else None
    return RepairOut(
        id=r.id,
        repair_number=r.repair_number,
        ticket_id=r.ticket_id,
        ticket_number=r.ticket.ticket_number if r.ticket else None,
        ticket_status=r.ticket.status.value if r.ticket else "",
        origin=r.origin,
        blocks_room=r.blocks_room,
        room_id=r.room_id,
        room_number=r.room.room_number,
        floor=r.room.floor,
        room_occupancy=r.room.occupancy_status.value,
        room_status=r.room.operational_status.value,
        status=r.status,
        priority=r.priority,
        reported_defect=r.reported_defect,
        assigned_engineer=user_brief(r.assigned_engineer),
        created_by=user_brief(r.created_by),
        diagnosis=r.diagnosis,
        repair_notes=r.repair_notes,
        requires_recleaning=r.requires_recleaning,
        reopen_count=r.reopen_count,
        last_reopen_reason=r.last_reopen_reason,
        started_at=r.started_at,
        completed_at=r.completed_at,
        created_at=r.created_at,
        updated_at=r.updated_at,
        progress=compute_progress(current.results) if current else None,
    )
