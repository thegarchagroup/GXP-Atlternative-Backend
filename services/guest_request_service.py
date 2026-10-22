"""Front desk guest requests ("water bottle for 201"), assigned by the HK supervisor to a room attendant."""
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.exceptions import ForbiddenError, NotFoundError, ValidationFailedError, WorkflowError
from database.base import utcnow
from models.enums import OPEN_REQUEST_STATUSES, Priority, RequestStatus, Role
from models.guest_request import GuestRequest
from models.user import User
from repositories import room_repository
from services import audit_service


def _log(db, actor, req: GuestRequest, action: str, message: str, details=None, from_status=None):
    audit_service.log(db, actor=actor, action=action, message=message, entity_type="guest_request", entity_id=req.id,
                      room_id=req.room_id, from_status=from_status, to_status=req.status, details=details)


def get(db: Session, request_id: int, *, lock: bool = False) -> GuestRequest:
    stmt = select(GuestRequest).where(GuestRequest.id == request_id)
    req = db.scalar(stmt.with_for_update() if lock else stmt)
    if not req:
        raise NotFoundError("Request not found.")
    return req


def create(db: Session, actor: User, *, room_id: int, description: str, priority: Priority) -> GuestRequest:
    room = room_repository.get(db, room_id)
    if not room or not room.is_active:
        raise NotFoundError("Room not found.")
    text = description.strip()
    if len(text) < 2:
        raise ValidationFailedError("Describe the request.", code="DESCRIPTION_REQUIRED")
    req = GuestRequest(room_id=room.id, description=text[:2000], priority=priority, status=RequestStatus.NEW,
                       created_by_id=actor.id)
    db.add(req)
    db.flush()
    req.request_number = f"GR-{utcnow():%Y%m%d}-{req.id:05d}"
    _log(db, actor, req, "REQUEST_CREATED", f"Request {req.request_number} for room {room.room_number}: {text[:80]}")
    db.commit()
    db.refresh(req)
    return req


def search(db: Session, user: User, *, statuses: Optional[list[RequestStatus]], day: Optional[date],
           room_id: Optional[int], mine: bool = False) -> list[GuestRequest]:
    stmt = select(GuestRequest)
    if mine or user.role == Role.ROOM_ATTENDANT:
        stmt = stmt.where(GuestRequest.assigned_ra_id == user.id)
    if statuses:
        stmt = stmt.where(GuestRequest.status.in_(statuses))
    if day:
        start = datetime.combine(day, time.min)
        stmt = stmt.where(GuestRequest.created_at >= start - timedelta(hours=14), GuestRequest.created_at < start + timedelta(days=1, hours=14))
    if room_id:
        stmt = stmt.where(GuestRequest.room_id == room_id)
    return list(db.scalars(stmt.order_by(GuestRequest.created_at.desc(), GuestRequest.id.desc()).limit(500)).unique().all())


def assign(db: Session, actor: User, request_id: int, ra_id: int) -> GuestRequest:
    req = get(db, request_id, lock=True)
    if req.status not in (RequestStatus.NEW, RequestStatus.ASSIGNED):
        raise WorkflowError("Only requests that have not been started can be assigned.", code="REQUEST_STARTED")
    ra = db.get(User, ra_id)
    if not ra or ra.is_deleted or not ra.is_active or ra.role != Role.ROOM_ATTENDANT:
        raise ValidationFailedError("Choose an active room attendant.", code="INVALID_ASSIGNEE")
    previous = req.assigned_ra.display_name if req.assigned_ra else None
    before = req.status
    req.assigned_ra_id = ra.id
    req.assigned_ra = ra
    req.assigned_by_id = actor.id
    req.assigned_at = utcnow()
    req.status = RequestStatus.ASSIGNED
    _log(db, actor, req, "REQUEST_ASSIGNED",
         f"Request {req.request_number} {'reassigned from ' + previous + ' ' if previous else ''}to {ra.display_name}", from_status=before)
    db.commit()
    return req


def _own(db: Session, ra: User, request_id: int) -> GuestRequest:
    req = get(db, request_id, lock=True)
    if ra.role != Role.ROOM_ATTENDANT or req.assigned_ra_id != ra.id:
        raise ForbiddenError("This request is not assigned to you.", code="NOT_ASSIGNEE")
    return req


def start(db: Session, ra: User, request_id: int) -> GuestRequest:
    req = _own(db, ra, request_id)
    if req.status != RequestStatus.ASSIGNED:
        raise WorkflowError("This request has already been started or finished.")
    req.status = RequestStatus.IN_PROGRESS
    req.started_at = utcnow()
    _log(db, ra, req, "REQUEST_STARTED", f"{ra.display_name} started request {req.request_number}", from_status=RequestStatus.ASSIGNED)
    db.commit()
    return req


def complete(db: Session, ra: User, request_id: int, note: Optional[str]) -> GuestRequest:
    req = _own(db, ra, request_id)
    if req.status not in (RequestStatus.ASSIGNED, RequestStatus.IN_PROGRESS):
        raise WorkflowError("This request is already finished.")
    before = req.status
    now = utcnow()
    req.started_at = req.started_at or now
    req.completed_at = now
    req.completion_note = (note or "").strip() or None
    req.status = RequestStatus.DONE
    _log(db, ra, req, "REQUEST_DONE", f"{ra.display_name} completed request {req.request_number} for room {req.room.room_number}",
         details={"note": req.completion_note} if req.completion_note else None, from_status=before)
    db.commit()
    return req


def cancel(db: Session, actor: User, request_id: int, reason: str) -> GuestRequest:
    req = get(db, request_id, lock=True)
    if req.status not in OPEN_REQUEST_STATUSES:
        raise WorkflowError("Only open requests can be cancelled.")
    before = req.status
    req.status = RequestStatus.CANCELLED
    req.cancelled_at = utcnow()
    req.cancel_reason = reason
    _log(db, actor, req, "REQUEST_CANCELLED", f"Request {req.request_number} cancelled", details={"reason": reason}, from_status=before)
    db.commit()
    return req
