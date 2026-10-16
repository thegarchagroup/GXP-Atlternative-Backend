from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.permissions import require_admin, require_any
from database.connection import get_db
from models.enums import OccupancyStatus, OperationalStatus
from models.user import User
from repositories import room_repository
from schemas.common import Page
from schemas.room_schema import (
    RoomCreate, RoomOccupancyUpdate, RoomOut, RoomStatusOverride, RoomTypeCreate, RoomTypeOut, RoomTypeUpdate,
    RoomUpdate, room_out,
)
from schemas.turnover_schema import ticket_out, timeline_entry
from services import room_service

router = APIRouter(prefix="/api/v1/rooms", tags=["Rooms"])


# Room types (declared before /{room_id} routes)
@router.get("/types", response_model=list[RoomTypeOut])
def list_room_types(include_inactive: bool = True, _: User = Depends(require_any), db: Session = Depends(get_db)):
    return [RoomTypeOut.model_validate(t) for t in room_repository.list_room_types(db, include_inactive)]


@router.post("/types", response_model=RoomTypeOut, status_code=201)
def create_room_type(body: RoomTypeCreate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    return RoomTypeOut.model_validate(room_service.create_room_type(db, actor, body))


@router.put("/types/{type_id}", response_model=RoomTypeOut)
def update_room_type(type_id: int, body: RoomTypeUpdate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    return RoomTypeOut.model_validate(room_service.update_room_type(db, actor, type_id, body))


@router.get("", response_model=Page[RoomOut])
def list_rooms(
    search: Optional[str] = None,
    floor: Optional[int] = None,
    operational_status: Optional[OperationalStatus] = None,
    occupancy_status: Optional[OccupancyStatus] = None,
    assigned_user_id: Optional[int] = None,
    room_type_id: Optional[int] = None,
    ticket_created_from: Optional[date] = None,
    ticket_created_to: Optional[date] = None,
    include_inactive: bool = False,
    sort: Literal["room_number", "floor", "operational_status", "updated_at"] = "room_number",
    order: Literal["asc", "desc"] = "asc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows, total = room_repository.search(
        db, search=search, floor=floor, operational_status=operational_status, occupancy_status=occupancy_status,
        assigned_user_id=assigned_user_id, room_type_id=room_type_id, ticket_created_from=ticket_created_from,
        ticket_created_to=ticket_created_to, include_inactive=include_inactive, sort=sort, order=order,
        page=page, page_size=page_size,
    )
    return Page(items=[room_out(r) for r in rows], total=total, page=page, page_size=page_size)


@router.post("", response_model=RoomOut, status_code=201)
def create_room(body: RoomCreate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    return room_out(room_service.create_room(db, actor, body))


@router.get("/{room_id}", response_model=RoomOut)
def get_room(room_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return room_out(room_service.get_room(db, room_id))


@router.put("/{room_id}", response_model=RoomOut)
def update_room(room_id: int, body: RoomUpdate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    return room_out(room_service.update_room(db, actor, room_id, body))


@router.patch("/{room_id}/status", response_model=RoomOut)
def override_status(room_id: int, body: RoomStatusOverride, actor: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    return room_out(room_service.override_status(db, actor, room_id, body))


@router.patch("/{room_id}/occupancy", response_model=RoomOut)
def set_occupancy(room_id: int, body: RoomOccupancyUpdate, actor: User = Depends(require_admin),
                  db: Session = Depends(get_db)):
    return room_out(room_service.set_occupancy(db, actor, room_id, body))


@router.get("/{room_id}/history")
def room_history(room_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    room, tickets, logs = room_service.history(db, room_id)
    return {
        "room": room_out(room).model_dump(mode="json"),
        "tickets": [ticket_out(t).model_dump(mode="json") for t in tickets],
        "activity": [timeline_entry(log).model_dump(mode="json") for log in logs],
    }
