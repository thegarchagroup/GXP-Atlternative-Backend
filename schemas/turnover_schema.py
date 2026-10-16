from typing import Optional

from pydantic import BaseModel, Field

from models.enums import OperationalStatus, Priority, TicketStatus
from schemas.common import UserBrief, UTCDateTime, user_brief
from schemas.inspection_schema import InspectionSessionOut, Progress, compute_progress
from schemas.repair_schema import RepairOut


class TicketCreate(BaseModel):
    room_id: int
    priority: Priority = Priority.NORMAL
    notes: Optional[str] = Field(default=None, max_length=2000)
    assigned_housekeeper_id: Optional[int] = None
    allow_duplicate: bool = False
    duplicate_reason: Optional[str] = Field(default=None, max_length=1000)


class TicketAssignRequest(BaseModel):
    housekeeper_id: int
    reason: Optional[str] = Field(default=None, max_length=1000)


class TicketCancelRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    room_status: OperationalStatus = OperationalStatus.OUT_OF_SERVICE


class TicketPriorityUpdate(BaseModel):
    priority: Priority


class SubmitRequest(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=2000)


class TicketOut(BaseModel):
    id: int
    ticket_number: Optional[str]
    room_id: int
    room_number: str
    floor: int
    room_type: str
    status: TicketStatus
    priority: Priority
    is_active: bool
    is_exception: bool
    needs_reclean: bool
    notes: Optional[str] = None
    assigned_housekeeper: Optional[UserBrief] = None
    created_by: Optional[UserBrief] = None
    released_by: Optional[UserBrief] = None
    housekeeping_started_at: Optional[UTCDateTime] = None
    housekeeping_completed_at: Optional[UTCDateTime] = None
    released_at: Optional[UTCDateTime] = None
    cancelled_at: Optional[UTCDateTime] = None
    cancel_reason: Optional[str] = None
    created_at: UTCDateTime
    updated_at: UTCDateTime
    progress: Optional[Progress] = None
    open_repairs: int = 0


class AssignmentOut(BaseModel):
    id: int
    department: str
    repair_id: Optional[int] = None
    assignee: Optional[UserBrief]
    previous_assignee: Optional[UserBrief] = None
    assigned_by: Optional[UserBrief]
    reason: Optional[str] = None
    assigned_at: UTCDateTime


class ReadinessOut(BaseModel):
    ready: bool
    blockers: list[str]
    can_release: bool


class TicketDetailOut(TicketOut):
    sessions: list[InspectionSessionOut] = []
    repairs: list[RepairOut] = []
    assignments: list[AssignmentOut] = []
    readiness: Optional[ReadinessOut] = None


class TimelineEntry(BaseModel):
    id: int
    action: str
    message: str
    actor: Optional[UserBrief] = None
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    details: Optional[dict] = None
    created_at: UTCDateTime


def ticket_out(t) -> TicketOut:
    hk_sessions = [s for s in t.sessions if s.repair_id is None]
    current = hk_sessions[-1] if hk_sessions else None
    from models.enums import OPEN_REPAIR_STATUSES

    return TicketOut(
        id=t.id,
        ticket_number=t.ticket_number,
        room_id=t.room_id,
        room_number=t.room.room_number,
        floor=t.room.floor,
        room_type=t.room.room_type.name if t.room.room_type else "",
        status=t.status,
        priority=t.priority,
        is_active=t.is_active,
        is_exception=t.is_exception,
        needs_reclean=t.needs_reclean,
        notes=t.notes,
        assigned_housekeeper=user_brief(t.assigned_housekeeper),
        created_by=user_brief(t.created_by),
        released_by=user_brief(t.released_by),
        housekeeping_started_at=t.housekeeping_started_at,
        housekeeping_completed_at=t.housekeeping_completed_at,
        released_at=t.released_at,
        cancelled_at=t.cancelled_at,
        cancel_reason=t.cancel_reason,
        created_at=t.created_at,
        updated_at=t.updated_at,
        progress=compute_progress(current.results) if current else None,
        open_repairs=sum(1 for r in t.repairs if r.status in OPEN_REPAIR_STATUSES),
    )


def timeline_entry(log) -> TimelineEntry:
    return TimelineEntry(
        id=log.id, action=log.action, message=log.message, actor=user_brief(log.actor),
        from_status=log.from_status, to_status=log.to_status, details=log.details, created_at=log.created_at,
    )
