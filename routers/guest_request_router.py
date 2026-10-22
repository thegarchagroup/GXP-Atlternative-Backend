from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.permissions import require_roles
from database.connection import get_db
from models.enums import RequestStatus, Role
from models.user import User
from schemas.guest_request_schema import (
    GuestRequestAssign, GuestRequestCancel, GuestRequestCreate, GuestRequestDone, GuestRequestOut, request_out,
)
from services import guest_request_service as svc

router = APIRouter(prefix="/api/v1/requests", tags=["Guest requests"])
front_desk = require_roles(Role.ADMIN)
hk_supervisor = require_roles(Role.HK_SUPERVISOR)
attendant = require_roles(Role.ROOM_ATTENDANT)
viewers = require_roles(Role.ADMIN, Role.HK_SUPERVISOR, Role.ROOM_ATTENDANT)
managers = require_roles(Role.ADMIN, Role.HK_SUPERVISOR)


@router.post("", response_model=GuestRequestOut, status_code=201)
def create_request(body: GuestRequestCreate, actor: User = Depends(front_desk), db: Session = Depends(get_db)):
    """Front desk raises a free-text request for a room. The HK supervisor assigns it to a room attendant."""
    return request_out(svc.create(db, actor, room_id=body.room_id, description=body.description, priority=body.priority))


@router.get("", response_model=list[GuestRequestOut])
def list_requests(status: Optional[list[RequestStatus]] = Query(None), day: Optional[date] = None,
                  room_id: Optional[int] = None, user: User = Depends(viewers), db: Session = Depends(get_db)):
    """Front desk and HK supervisor see every request; a room attendant sees only theirs."""
    return [request_out(r) for r in svc.search(db, user, statuses=status, day=day, room_id=room_id)]


@router.post("/{request_id}/assign", response_model=GuestRequestOut)
def assign_request(request_id: int, body: GuestRequestAssign, actor: User = Depends(hk_supervisor), db: Session = Depends(get_db)):
    return request_out(svc.assign(db, actor, request_id, body.ra_id))


@router.post("/{request_id}/start", response_model=GuestRequestOut)
def start_request(request_id: int, ra: User = Depends(attendant), db: Session = Depends(get_db)):
    return request_out(svc.start(db, ra, request_id))


@router.post("/{request_id}/done", response_model=GuestRequestOut)
def complete_request(request_id: int, body: GuestRequestDone, ra: User = Depends(attendant), db: Session = Depends(get_db)):
    return request_out(svc.complete(db, ra, request_id, body.note))


@router.post("/{request_id}/cancel", response_model=GuestRequestOut)
def cancel_request(request_id: int, body: GuestRequestCancel, actor: User = Depends(managers), db: Session = Depends(get_db)):
    return request_out(svc.cancel(db, actor, request_id, body.reason))
