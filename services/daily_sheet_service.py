"""Daily housekeeping: the uploaded task sheet, room attendant assignment, the runsheet and the form."""
import re
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import settings
from core.exceptions import ForbiddenError, NotFoundError, ValidationFailedError, WorkflowError
from database.base import utcnow
from models.daily_sheet import DailySheet, DailySheetRoom
from models.enums import (
    ChecklistType, DailyRoomStatus, ItemResult, OccupancyStatus, OperationalStatus, Priority, RepairStatus, Role,
    SessionKind, SessionOutcome, SessionStatus,
)
from models.inspection import InspectionResult, InspectionSession
from models.repair import RepairRequest
from models.room import Room, RoomType
from models.user import User
from repositories import checklist_repository, room_repository
from schemas.inspection_schema import ResultUpdate
from services import audit_service
from services.task_sheet_parser import parse_task_sheet

FORM_TYPES = [ChecklistType.HOUSEKEEPING_CLEANING, ChecklistType.HOUSEKEEPING_INSPECTION]
MAX_PDF_MB = 15
ENGINEERING_ROOM_STATUSES = {OperationalStatus.ENGINEERING_REQUIRED, OperationalStatus.ENGINEERING_ASSIGNED,
                             OperationalStatus.ENGINEERING_IN_PROGRESS}


def hotel_today() -> date:
    return datetime.now(timezone.utc).astimezone(ZoneInfo(settings.HOTEL_TIMEZONE)).date()


def _log(db, actor, action, message, entry: Optional[DailySheetRoom] = None, sheet: Optional[DailySheet] = None,
         details=None, repair_id=None):
    audit_service.log(db, actor=actor, action=action, message=message,
                      entity_type="daily_room" if entry is not None else "daily_sheet",
                      entity_id=entry.id if entry is not None else (sheet.id if sheet is not None else None),
                      room_id=entry.room_id if entry is not None else None, repair_id=repair_id, details=details)


# --------------------------------------------------------------------------- room status

def _room_follows_sheet(room: Optional[Room], entry: DailySheetRoom) -> bool:
    """Only today's sheet moves the live room status, and never a room that is out of service,
    in an old-style turnover, or blocked by an open engineering repair."""
    if room is None or entry.sheet.task_date != hotel_today():
        return False
    if room.active_ticket_id or room.operational_status == OperationalStatus.OUT_OF_SERVICE:
        return False
    return room.operational_status not in ENGINEERING_ROOM_STATUSES


def _sync_room(room: Optional[Room], entry: DailySheetRoom) -> None:
    if not _room_follows_sheet(room, entry):
        return
    if entry.fo_status == "VAC":
        room.occupancy_status = OccupancyStatus.VACANT
    elif entry.fo_status == "OCC":
        room.occupancy_status = OccupancyStatus.OCCUPIED
    if entry.status == DailyRoomStatus.PENDING:
        room.operational_status = (OperationalStatus.HOUSEKEEPING_ASSIGNED if entry.assigned_ra_id
                                   else OperationalStatus.AWAITING_HOUSEKEEPING)
        room.assigned_housekeeper_id = entry.assigned_ra_id
    elif entry.status == DailyRoomStatus.IN_PROGRESS:
        room.operational_status = OperationalStatus.HOUSEKEEPING_IN_PROGRESS
        room.assigned_housekeeper_id = entry.assigned_ra_id


# --------------------------------------------------------------------------- upload

def get_sheet(db: Session, sheet_id: int) -> DailySheet:
    sheet = db.get(DailySheet, sheet_id)
    if not sheet:
        raise NotFoundError("Task sheet not found.")
    return sheet


def get_sheet_by_date(db: Session, task_date: date) -> Optional[DailySheet]:
    return db.scalar(select(DailySheet).where(DailySheet.task_date == task_date))


def upload(db: Session, actor: User, data: bytes, filename: str, task_date: Optional[date]) -> tuple[DailySheet, dict]:
    if len(data) > MAX_PDF_MB * 1024 * 1024:
        raise ValidationFailedError(f"The PDF is larger than {MAX_PDF_MB} MB.", code="FILE_TOO_LARGE")
    try:
        parsed = parse_task_sheet(data)
    except ValueError as exc:
        raise ValidationFailedError(str(exc), code="TASK_SHEET_UNREADABLE")
    the_date = task_date or parsed.task_date or hotel_today()

    sheet = get_sheet_by_date(db, the_date)
    if sheet is None:
        sheet = DailySheet(task_date=the_date)
        db.add(sheet)
        db.flush()
    sheet.source_filename = (filename or "task-sheet.pdf")[:255]
    sheet.uploaded_by_id = actor.id
    sheet.last_uploaded_at = utcnow()
    sheet.upload_count = (sheet.upload_count or 0) + 1

    existing = {e.room_number: e for e in sheet.rooms}
    rooms_by_number = {r.room_number.lower(): r for r in db.scalars(select(Room)).all()}
    added = updated = removed = 0
    seen = set()
    for pr in parsed.rooms:
        seen.add(pr.room_number)
        entry = existing.get(pr.room_number)
        if entry is None:
            entry = DailySheetRoom(sheet=sheet, room_number=pr.room_number, status=DailyRoomStatus.PENDING)
            db.add(entry)
            added += 1
        else:
            updated += 1
        room = rooms_by_number.get(pr.room_number.lower())
        entry.room_id = room.id if room else None
        entry.room = room
        entry.sheet_no = pr.sheet_no
        entry.room_type_code = pr.room_type
        entry.hk_status = pr.hk_status
        entry.fo_status = pr.fo_status
        entry.reservation_status = pr.reservation_status
        entry.arrival_date = pr.arrival
        entry.departure_date = pr.departure
        entry.arrival_today = pr.arrival_today
        entry.on_latest_upload = True
    for number, entry in existing.items():
        if number in seen:
            continue
        if entry.status == DailyRoomStatus.PENDING and not entry.assigned_ra_id:
            db.delete(entry)
            removed += 1
        else:
            entry.on_latest_upload = False  # keep work already assigned or done
    db.flush()
    db.expire(sheet, ["rooms"])
    for entry in sheet.rooms:
        _sync_room(entry.room, entry)
    _log(db, actor, "TASK_SHEET_UPLOADED",
         f"Task sheet for {the_date:%d %b %Y} uploaded ({len(parsed.rooms)} rooms)", sheet=sheet,
         details={"file": sheet.source_filename, "added": added, "updated": updated, "removed": removed})
    db.commit()
    db.refresh(sheet)
    return sheet, {"added": added, "updated": updated, "removed": removed, "rooms_in_file": len(parsed.rooms)}


def _floor_from_number(number: str) -> int:
    digits = re.sub(r"\D", "", number)
    return int(digits[:-2]) if len(digits) >= 3 else 0


def add_missing_rooms(db: Session, actor: User, sheet_id: int) -> int:
    """Create rooms (and room types from their codes) for task-sheet rooms not yet in the system."""
    sheet = get_sheet(db, sheet_id)
    missing = [e for e in sheet.rooms if e.room_id is None]
    types = {t.name.upper(): t for t in db.scalars(select(RoomType)).all()}
    created = 0
    for entry in missing:
        room = room_repository.get_by_number(db, entry.room_number)
        if room is None:
            code = (entry.room_type_code or "STANDARD").upper()
            rtype = types.get(code)
            if rtype is None:
                rtype = RoomType(name=code, category="From task sheet")
                db.add(rtype)
                db.flush()
                types[code] = rtype
            room = Room(room_number=entry.room_number, floor=_floor_from_number(entry.room_number),
                        room_type_id=rtype.id, occupancy_status=OccupancyStatus.VACANT,
                        operational_status=OperationalStatus.AWAITING_HOUSEKEEPING)
            db.add(room)
            db.flush()
            created += 1
        entry.room_id = room.id
        entry.room = room
        _sync_room(room, entry)
    if missing:
        _log(db, actor, "TASK_SHEET_ROOMS_ADDED", f"Added {created} room(s) from the task sheet", sheet=sheet,
             details={"rooms": [e.room_number for e in missing]})
    db.commit()
    return created


def move_sheet(db: Session, actor: User, sheet_id: int, new_date: date) -> DailySheet:
    """Re-date a sheet (e.g. a PDF printed with another day's date), keeping assignments and work."""
    from core.exceptions import ConflictError

    sheet = get_sheet(db, sheet_id)
    if sheet.task_date == new_date:
        return sheet
    other = get_sheet_by_date(db, new_date)
    if other is not None:
        raise ConflictError(f"There is already a task sheet for {new_date:%d %b %Y}. Open that date instead.",
                            code="SHEET_DATE_TAKEN")
    old = sheet.task_date
    sheet.task_date = new_date
    db.flush()
    for entry in sheet.rooms:
        _sync_room(entry.room, entry)
    _log(db, actor, "TASK_SHEET_REDATED", f"Task sheet moved from {old:%d %b %Y} to {new_date:%d %b %Y}", sheet=sheet,
         details={"from": old.isoformat(), "to": new_date.isoformat()})
    db.commit()
    db.refresh(sheet)
    return sheet


def my_dates(db: Session, ra: User, limit: int = 30) -> list[dict]:
    """Dates on which this room attendant has rooms, newest first, with how many are finished."""
    from sqlalchemy import case, func
    rows = db.execute(
        select(DailySheet.task_date, func.count(DailySheetRoom.id),
               func.sum(case((DailySheetRoom.status == DailyRoomStatus.DONE, 1), else_=0)))
        .join(DailySheetRoom, DailySheetRoom.sheet_id == DailySheet.id)
        .where(DailySheetRoom.assigned_ra_id == ra.id)
        .group_by(DailySheet.task_date).order_by(DailySheet.task_date.desc()).limit(limit)
    ).all()
    return [{"task_date": d, "rooms": int(n), "done": int(done or 0)} for d, n, done in rows]


# --------------------------------------------------------------------------- assignment

def _active_ra(db: Session, ra_id: int) -> User:
    ra = db.get(User, ra_id)
    if not ra or ra.is_deleted or not ra.is_active or ra.role != Role.ROOM_ATTENDANT:
        raise ValidationFailedError("Choose an active room attendant.", code="INVALID_ASSIGNEE")
    return ra


def assign(db: Session, actor: User, sheet_id: int, *, entry_ids: Optional[list[int]], sheet_no: Optional[str],
           ra_id: Optional[int]) -> int:
    sheet = get_sheet(db, sheet_id)
    ra = _active_ra(db, ra_id) if ra_id else None
    if entry_ids:
        wanted = set(entry_ids)
        targets = [e for e in sheet.rooms if e.id in wanted]
        if len(targets) != len(wanted):
            raise ValidationFailedError("Some rooms are not on this task sheet.")
    elif sheet_no:
        targets = [e for e in sheet.rooms if e.sheet_no == sheet_no]
        if not targets:
            raise ValidationFailedError(f"There is no task sheet {sheet_no} on this date.")
    else:
        raise ValidationFailedError("Choose rooms or a task sheet number.")
    blocked = [e.room_number for e in targets if e.status != DailyRoomStatus.PENDING and e.assigned_ra_id != (ra.id if ra else None)]
    if blocked:
        raise WorkflowError(f"Already started or finished, so they can't be reassigned: {', '.join(blocked)}.",
                            code="ROOM_ALREADY_STARTED")
    now = utcnow()
    for e in targets:
        e.assigned_ra_id = ra.id if ra else None
        e.assigned_ra = ra
        e.assigned_at = now if ra else None
        _sync_room(e.room, e)
    who = ra.display_name if ra else "nobody"
    _log(db, actor, "TASK_SHEET_ASSIGNED",
         f"{len(targets)} room(s) assigned to {who}" + (f" (sheet {sheet_no})" if sheet_no and not entry_ids else ""),
         sheet=sheet, details={"rooms": [e.room_number for e in targets], "room_attendant": who})
    db.commit()
    return len(targets)


# --------------------------------------------------------------------------- runsheet and form

def priority_key(e: DailySheetRoom):
    """Arrivals first, then vacant (departed) rooms, then due outs, then stayovers. Finished rooms last."""
    if e.status == DailyRoomStatus.DONE:
        bucket = 9
    elif e.arrival_today:
        bucket = 0
    elif e.fo_status == "VAC":
        bucket = 1
    elif e.reservation_status.lower() == "due out":
        bucket = 2
    else:
        bucket = 3
    return (bucket, e.room_number)


def runsheet(db: Session, ra: User, task_date: date) -> list[DailySheetRoom]:
    sheet = get_sheet_by_date(db, task_date)
    if sheet is None:
        return []
    return sorted([e for e in sheet.rooms if e.assigned_ra_id == ra.id], key=priority_key)


def get_entry(db: Session, user: User, entry_id: int) -> DailySheetRoom:
    entry = db.get(DailySheetRoom, entry_id)
    if not entry:
        raise NotFoundError("Room not found on the task sheet.")
    if user.role in (Role.HK_SUPERVISOR, Role.ADMIN):
        return entry
    if user.role == Role.ROOM_ATTENDANT and entry.assigned_ra_id == user.id:
        return entry
    raise ForbiddenError("This room is not on your runsheet.", code="NOT_ASSIGNEE")


def current_session(entry: DailySheetRoom) -> Optional[InspectionSession]:
    sessions = [s for s in entry.sessions if s.status != SessionStatus.SUPERSEDED]
    return sessions[-1] if sessions else None


def _own_entry(db: Session, ra: User, entry_id: int) -> DailySheetRoom:
    entry = db.get(DailySheetRoom, entry_id)
    if not entry:
        raise NotFoundError("Room not found on the task sheet.")
    if ra.role != Role.ROOM_ATTENDANT or entry.assigned_ra_id != ra.id:
        raise ForbiddenError("This room is not on your runsheet.", code="NOT_ASSIGNEE")
    return entry


def start(db: Session, ra: User, entry_id: int) -> DailySheetRoom:
    entry = _own_entry(db, ra, entry_id)
    if entry.status != DailyRoomStatus.PENDING:
        raise WorkflowError("This room has already been started.", code="ALREADY_STARTED")
    if entry.room_id is None:
        raise WorkflowError(f"Room {entry.room_number} is not set up in the system yet. "
                            "Ask your supervisor to add the task sheet's rooms.", code="ROOM_NOT_SET_UP")
    items = checklist_repository.active_items_for(db, FORM_TYPES, entry.room.room_type_id)
    if not items:
        raise WorkflowError("The room form has no items yet. Ask your supervisor to set it up.", code="NO_CHECKLIST")
    session = InspectionSession(ticket_id=None, repair_id=None, daily_room_id=entry.id, kind=SessionKind.HOUSEKEEPING,
                                round_number=1, status=SessionStatus.IN_PROGRESS, inspector_id=ra.id, started_at=utcnow())
    db.add(session)
    for template, item in items:
        db.add(InspectionResult(
            session=session, template_item_id=item.id, checklist_type=template.checklist_type, item_name=item.name,
            description=item.description, category=item.category, is_mandatory=item.is_mandatory,
            allow_not_applicable=item.allow_not_applicable, display_order=item.display_order,
            reference_instructions=item.reference_instructions, result=ItemResult.PENDING))
    entry.status = DailyRoomStatus.IN_PROGRESS
    entry.started_at = utcnow()
    _sync_room(entry.room, entry)
    _log(db, ra, "ROOM_CLEAN_STARTED", f"{ra.display_name} started room {entry.room_number}", entry=entry)
    db.commit()
    db.expire(entry, ["sessions"])
    return entry


def _open_session(entry: DailySheetRoom) -> InspectionSession:
    session = current_session(entry)
    if entry.status != DailyRoomStatus.IN_PROGRESS or not session or session.status != SessionStatus.IN_PROGRESS:
        raise WorkflowError("Start the room before filling in the form.", code="NOT_STARTED")
    return session


def save(db: Session, ra: User, entry_id: int, items: list[ResultUpdate]) -> DailySheetRoom:
    from services import turnover_service as wf

    entry = _own_entry(db, ra, entry_id)
    wf.save_results(db, _open_session(entry), ra, items)
    db.commit()
    db.expire(entry, ["sessions"])
    return entry


def finish(db: Session, ra: User, entry_id: int, items: list[ResultUpdate], notes: Optional[str]) -> DailySheetRoom:
    from services import engineering_service, turnover_service as wf

    entry = _own_entry(db, ra, entry_id)
    session = _open_session(entry)
    if items:
        wf.save_results(db, session, ra, items)
        db.flush()
        db.expire(session, ["results"])
    problems = wf.validate_for_submit(session)
    failed = [r for r in session.results if r.result == ItemResult.FAIL]
    for r in failed:
        if not r.attachments:
            problems.append(f"'{r.item_name}' failed: take a photo of the problem.")
    if problems:
        db.commit()  # keep what was entered
        raise ValidationFailedError("The form is not complete.", code="FORM_INCOMPLETE", details=problems)

    now = utcnow()
    session.status = SessionStatus.SUBMITTED
    session.submitted_at = now
    session.submitted_by_id = ra.id
    session.notes = notes
    session.outcome = SessionOutcome.FAIL if failed else SessionOutcome.PASS
    entry.status = DailyRoomStatus.DONE
    entry.finished_at = now
    entry.outcome = session.outcome
    room = entry.room
    repair = None
    if failed:
        defect = "; ".join(f"{r.item_name}: {r.remarks}" for r in failed)
        if notes:
            defect += f"\nRoom attendant note: {notes}"
        vacant = entry.fo_status == "VAC" or room.occupancy_status == OccupancyStatus.VACANT
        repair = RepairRequest(room_id=room.id, ticket_id=None, source_session_id=session.id, status=RepairStatus.NEW,
                               priority=Priority.HIGH if entry.arrival_today else Priority.NORMAL,
                               reported_defect=defect[:5000], created_by_id=ra.id,
                               blocks_room=vacant and not room.active_ticket_id)
        db.add(repair)
        db.flush()
        repair.repair_number = f"RR-{now:%Y%m%d}-{repair.id:05d}"
        for r in failed:
            for att in r.attachments:
                att.repair_id = repair.id
    follows = _room_follows_sheet(room, entry)
    if follows or (room.operational_status == OperationalStatus.HOUSEKEEPING_IN_PROGRESS and not room.active_ticket_id):
        room.operational_status = OperationalStatus.READY_FOR_GUEST
        room.assigned_housekeeper_id = None
        room.last_ready_at = now
    room.last_inspection_at = now
    if repair is not None:
        engineering_service.sync_room_for_direct_repairs(db, room)
    _log(db, ra, "ROOM_CLEAN_FINISHED",
         f"{ra.display_name} finished room {entry.room_number}" +
         (f"; {len(failed)} item(s) failed, repair {repair.repair_number} sent to Engineering" if repair else "; all items passed"),
         entry=entry, repair_id=repair.id if repair else None,
         details={"failed_items": [r.item_name for r in failed]} if failed else None)
    if repair is not None:
        audit_service.log(db, actor=ra, action="REPAIR_CREATED", entity_type="repair", entity_id=repair.id,
                          repair_id=repair.id, room_id=room.id, to_status=RepairStatus.NEW,
                          message=f"Repair {repair.repair_number} raised from room {entry.room_number} by {ra.display_name}",
                          details={"failed_items": [r.item_name for r in failed]})
    db.commit()
    db.expire(entry, ["sessions"])
    return entry


def sheet_summary(sheet: DailySheet) -> dict:
    rooms = sheet.rooms
    return {
        "total": len(rooms),
        "unassigned": sum(1 for e in rooms if not e.assigned_ra_id),
        "pending": sum(1 for e in rooms if e.status == DailyRoomStatus.PENDING),
        "in_progress": sum(1 for e in rooms if e.status == DailyRoomStatus.IN_PROGRESS),
        "done": sum(1 for e in rooms if e.status == DailyRoomStatus.DONE),
        "with_issues": sum(1 for e in rooms if e.outcome == SessionOutcome.FAIL),
        "arrivals": sum(1 for e in rooms if e.arrival_today),
        "missing_rooms": [e.room_number for e in rooms if e.room_id is None],
        "sheet_numbers": sorted({e.sheet_no for e in rooms if e.sheet_no}, key=lambda x: (not x.isdigit(), x.zfill(4))),
    }
