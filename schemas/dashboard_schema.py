from typing import Optional

from pydantic import BaseModel

from schemas.common import UserBrief, UTCDateTime


class FrontDeskSummary(BaseModel):
    total_rooms: int
    occupied: int
    vacant: int
    ready_for_guest: int
    awaiting_housekeeping: int
    housekeeping_assigned: int
    housekeeping_in_progress: int
    engineering_required: int
    engineering_assigned: int
    engineering_in_progress: int
    awaiting_final_verification: int
    out_of_service: int
    open_tickets: int
    open_repairs: int


class HousekeepingSummary(BaseModel):
    assigned: int
    pending: int
    in_progress: int
    submitted_for_engineering: int
    completed: int


class EngineeringSummary(BaseModel):
    new_requests: int
    assigned: int
    in_progress: int
    awaiting_verification: int
    completed: int
    reopened: int


class NotificationOut(BaseModel):
    id: int
    action: str
    message: str
    ticket_id: Optional[int] = None
    repair_id: Optional[int] = None
    room_id: Optional[int] = None
    actor: Optional[UserBrief] = None
    created_at: UTCDateTime
