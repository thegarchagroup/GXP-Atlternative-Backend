from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.exceptions import NotFoundError
from core.permissions import require_roles
from database.connection import get_db
from models.daily_sheet import DailySheet
from models.enums import Role
from models.repair import RepairRequest
from models.user import User
from schemas.daily_sheet_schema import (
    AssignRequest, DailyRoomDetailOut, DailyRoomOut, DailySheetOut, FinishRequest, FormSaveRequest, SheetListItem,
    SheetSummary, UploadResult, daily_room_detail, daily_room_out, sheet_out,
)
from services import daily_sheet_service as svc

router = APIRouter(prefix="/api/v1/housekeeping", tags=["Housekeeping: daily task sheet"])
supervisor = require_roles(Role.HK_SUPERVISOR)
supervisor_or_admin = require_roles(Role.HK_SUPERVISOR, Role.ADMIN)
attendant = require_roles(Role.ROOM_ATTENDANT)
viewer = require_roles(Role.HK_SUPERVISOR, Role.ADMIN, Role.ROOM_ATTENDANT)


@router.post("/daily-sheets/upload", response_model=UploadResult)
async def upload_task_sheet(file: UploadFile = File(...), task_date: Optional[date] = Form(None),
                            actor: User = Depends(supervisor), db: Session = Depends(get_db)):
    """Upload the day's Housekeeping Task Sheet PDF. The date is read from the sheet (or task_date).
    Re-uploading the same date updates it and keeps assignments and finished work."""
    data = await file.read(svc.MAX_PDF_MB * 1024 * 1024 + 1)
    sheet, counts = svc.upload(db, actor, data, file.filename or "", task_date)
    return UploadResult(**sheet_out(sheet), **counts)


@router.get("/daily-sheets", response_model=list[SheetListItem])
def list_task_sheets(limit: int = Query(60, ge=1, le=366), _: User = Depends(supervisor_or_admin),
                     db: Session = Depends(get_db)):
    """Uploaded task sheets, newest date first."""
    rows = db.scalars(select(DailySheet).order_by(DailySheet.task_date.desc()).limit(limit)).all()
    return [SheetListItem(id=s.id, task_date=s.task_date, upload_count=s.upload_count, last_uploaded_at=s.last_uploaded_at,
                          summary=SheetSummary(**svc.sheet_summary(s))) for s in rows]


@router.get("/daily-sheets/by-date/{task_date}", response_model=DailySheetOut)
def task_sheet_for_date(task_date: date, _: User = Depends(supervisor_or_admin), db: Session = Depends(get_db)):
    sheet = svc.get_sheet_by_date(db, task_date)
    if sheet is None:
        raise NotFoundError("No task sheet has been uploaded for this date.", code="NO_TASK_SHEET")
    return DailySheetOut(**sheet_out(sheet))


class MoveRequest(BaseModel):
    task_date: date


@router.post("/daily-sheets/{sheet_id}/move", response_model=DailySheetOut)
def move_task_sheet(sheet_id: int, body: MoveRequest, actor: User = Depends(supervisor), db: Session = Depends(get_db)):
    """Use a sheet for another date (e.g. "use as today's sheet"). Assignments and finished work are kept."""
    return DailySheetOut(**sheet_out(svc.move_sheet(db, actor, sheet_id, body.task_date)))


@router.post("/daily-sheets/{sheet_id}/add-missing-rooms")
def add_missing_rooms(sheet_id: int, actor: User = Depends(supervisor), db: Session = Depends(get_db)):
    """Create the task sheet's rooms that are not in the system yet (room types are created from their codes)."""
    return {"created": svc.add_missing_rooms(db, actor, sheet_id)}


@router.post("/daily-sheets/{sheet_id}/assign", response_model=DailySheetOut)
def assign_rooms(sheet_id: int, body: AssignRequest, actor: User = Depends(supervisor), db: Session = Depends(get_db)):
    """Assign rooms (entry_ids) or a whole task sheet (sheet_no) to a room attendant. ra_id null unassigns."""
    svc.assign(db, actor, sheet_id, entry_ids=body.entry_ids, sheet_no=body.sheet_no, ra_id=body.ra_id)
    return DailySheetOut(**sheet_out(svc.get_sheet(db, sheet_id)))


@router.get("/runsheet", response_model=list[DailyRoomOut])
def my_runsheet(task_date: Optional[date] = None, ra: User = Depends(attendant), db: Session = Depends(get_db)):
    """The signed-in room attendant's rooms for the day, in priority order."""
    return [daily_room_out(e) for e in svc.runsheet(db, ra, task_date or svc.hotel_today())]


def _detail(db, entry):
    ids = []
    s = svc.current_session(entry)
    if s is not None:
        ids = list(db.scalars(select(RepairRequest.id).where(RepairRequest.source_session_id == s.id)).all())
    return daily_room_detail(entry, ids)


@router.get("/runsheet/dates")
def my_runsheet_dates(ra: User = Depends(attendant), db: Session = Depends(get_db)):
    """Dates this room attendant has rooms on (newest first), so rooms on another day are never hidden."""
    return {"today": svc.hotel_today(), "dates": svc.my_dates(db, ra)}


@router.get("/runsheet/{entry_id}", response_model=DailyRoomDetailOut)
def runsheet_room(entry_id: int, user: User = Depends(viewer), db: Session = Depends(get_db)):
    return _detail(db, svc.get_entry(db, user, entry_id))


@router.post("/runsheet/{entry_id}/start", response_model=DailyRoomDetailOut)
def start_room(entry_id: int, ra: User = Depends(attendant), db: Session = Depends(get_db)):
    return _detail(db, svc.start(db, ra, entry_id))


@router.put("/runsheet/{entry_id}/form", response_model=DailyRoomDetailOut)
def save_form(entry_id: int, body: FormSaveRequest, ra: User = Depends(attendant), db: Session = Depends(get_db)):
    return _detail(db, svc.save(db, ra, entry_id, body.items))


@router.post("/runsheet/{entry_id}/finish", response_model=DailyRoomDetailOut)
def finish_room(entry_id: int, body: FinishRequest, ra: User = Depends(attendant), db: Session = Depends(get_db)):
    """Finish the room. Required items must be filled; a failed engineering item needs a remark and a photo,
    and raises a repair for Engineering."""
    return _detail(db, svc.finish(db, ra, entry_id, body.items, body.notes))
