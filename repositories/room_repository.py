from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from models.enums import OccupancyStatus, OperationalStatus
from models.room import Room, RoomType
from models.turnover import TurnoverTicket

SORTABLE = {
    "room_number": Room.room_number,
    "floor": Room.floor,
    "operational_status": Room.operational_status,
    "updated_at": Room.updated_at,
}


def get(db: Session, room_id: int, *, lock: bool = False) -> Optional[Room]:
    if lock:
        return db.scalar(select(Room).where(Room.id == room_id).with_for_update())
    return db.get(Room, room_id)


def get_by_number(db: Session, number: str) -> Optional[Room]:
    return db.scalar(select(Room).where(func.lower(Room.room_number) == number.strip().lower()))


def search(db: Session, *, search: Optional[str], floor: Optional[int], operational_status: Optional[OperationalStatus],
           occupancy_status: Optional[OccupancyStatus], assigned_user_id: Optional[int], room_type_id: Optional[int],
           ticket_created_from: Optional[date], ticket_created_to: Optional[date], include_inactive: bool,
           sort: str, order: str, page: int, page_size: int) -> tuple[list[Room], int]:
    stmt = select(Room)
    if not include_inactive:
        stmt = stmt.where(Room.is_active.is_(True))
    if search:
        stmt = stmt.where(Room.room_number.ilike(f"%{search.strip()}%"))
    if floor is not None:
        stmt = stmt.where(Room.floor == floor)
    if operational_status:
        stmt = stmt.where(Room.operational_status == operational_status)
    if occupancy_status:
        stmt = stmt.where(Room.occupancy_status == occupancy_status)
    if room_type_id:
        stmt = stmt.where(Room.room_type_id == room_type_id)
    if assigned_user_id:
        stmt = stmt.where(or_(Room.assigned_housekeeper_id == assigned_user_id, Room.assigned_engineer_id == assigned_user_id))
    if ticket_created_from or ticket_created_to:
        stmt = stmt.join(TurnoverTicket, TurnoverTicket.id == Room.active_ticket_id)
        if ticket_created_from:
            stmt = stmt.where(TurnoverTicket.created_at >= datetime.combine(ticket_created_from, time.min))
        if ticket_created_to:
            stmt = stmt.where(TurnoverTicket.created_at < datetime.combine(ticket_created_to + timedelta(days=1), time.min))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = SORTABLE.get(sort, Room.room_number)
    ordering = col.desc() if order == "desc" else col.asc()
    rows = db.scalars(stmt.order_by(ordering, Room.id).offset((page - 1) * page_size).limit(page_size)).unique().all()
    return list(rows), total


def list_room_types(db: Session, include_inactive: bool = True) -> list[RoomType]:
    stmt = select(RoomType).order_by(RoomType.name)
    if not include_inactive:
        stmt = stmt.where(RoomType.is_active.is_(True))
    return list(db.scalars(stmt).all())
