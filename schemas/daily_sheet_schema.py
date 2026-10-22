from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

from schemas.common import UserBrief, UTCDateTime, user_brief
from schemas.inspection_schema import InspectionSessionOut, Progress, ResultUpdate, compute_progress, session_out


class DailyRoomOut(BaseModel):
    id: int
    room_number: str
    room_id: Optional[int] = None
    room_known: bool
    sheet_no: str
    room_type_code: str
    hk_status: str
    fo_status: str
    reservation_status: str
    arrival_date: Optional[date] = None
    departure_date: Optional[date] = None
    arrival_today: bool
    status: str
    outcome: Optional[str] = None
    assigned_ra: Optional[UserBrief] = None
    assigned_at: Optional[UTCDateTime] = None
    started_at: Optional[UTCDateTime] = None
    finished_at: Optional[UTCDateTime] = None
    on_latest_upload: bool
    room_status: Optional[str] = None
    progress: Optional[Progress] = None


class DailyRoomDetailOut(DailyRoomOut):
    task_date: date
    session: Optional[InspectionSessionOut] = None
    repair_ids: list[int] = []


class SheetSummary(BaseModel):
    total: int
    unassigned: int
    pending: int
    in_progress: int
    done: int
    with_issues: int
    arrivals: int
    missing_rooms: list[str]
    sheet_numbers: list[str]


class DailySheetOut(BaseModel):
    id: int
    task_date: date
    source_filename: Optional[str] = None
    uploaded_by: Optional[UserBrief] = None
    last_uploaded_at: Optional[UTCDateTime] = None
    upload_count: int
    summary: SheetSummary
    rooms: list[DailyRoomOut]


class UploadResult(DailySheetOut):
    added: int
    updated: int
    removed: int
    rooms_in_file: int


class SheetListItem(BaseModel):
    id: int
    task_date: date
    upload_count: int
    last_uploaded_at: Optional[UTCDateTime] = None
    summary: SheetSummary


class AssignRequest(BaseModel):
    entry_ids: Optional[list[int]] = None
    sheet_no: Optional[str] = Field(default=None, max_length=20)
    ra_id: Optional[int] = None  # null = unassign


class FormSaveRequest(BaseModel):
    items: list[ResultUpdate] = []


class FinishRequest(FormSaveRequest):
    notes: Optional[str] = Field(default=None, max_length=2000)


def daily_room_out(e) -> DailyRoomOut:
    from services.daily_sheet_service import current_session
    s = current_session(e)
    return DailyRoomOut(
        id=e.id, room_number=e.room_number, room_id=e.room_id, room_known=e.room_id is not None, sheet_no=e.sheet_no,
        room_type_code=e.room_type_code, hk_status=e.hk_status, fo_status=e.fo_status,
        reservation_status=e.reservation_status, arrival_date=e.arrival_date, departure_date=e.departure_date,
        arrival_today=e.arrival_today, status=e.status.value, outcome=e.outcome.value if e.outcome else None,
        assigned_ra=user_brief(e.assigned_ra), assigned_at=e.assigned_at, started_at=e.started_at,
        finished_at=e.finished_at, on_latest_upload=e.on_latest_upload,
        room_status=e.room.operational_status.value if e.room else None,
        progress=compute_progress(s.results) if s else None,
    )


def daily_room_detail(e, repair_ids) -> DailyRoomDetailOut:
    from services.daily_sheet_service import current_session
    s = current_session(e)
    return DailyRoomDetailOut(**daily_room_out(e).model_dump(), task_date=e.sheet.task_date,
                              session=session_out(s) if s else None, repair_ids=repair_ids)


def sheet_out(sheet, rooms=None) -> dict:
    from services.daily_sheet_service import priority_key, sheet_summary
    return dict(id=sheet.id, task_date=sheet.task_date, source_filename=sheet.source_filename,
                uploaded_by=user_brief(sheet.uploaded_by), last_uploaded_at=sheet.last_uploaded_at,
                upload_count=sheet.upload_count, summary=SheetSummary(**sheet_summary(sheet)),
                rooms=[daily_room_out(e) for e in sorted(rooms if rooms is not None else sheet.rooms, key=priority_key)])
