from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from models.enums import OPEN_REPAIR_STATUSES, Priority, RepairStatus, TicketStatus
from models.repair import RepairRequest
from models.room import Room
from models.turnover import TurnoverTicket


def get_ticket(db: Session, ticket_id: int, *, lock: bool = False) -> Optional[TurnoverTicket]:
    stmt = select(TurnoverTicket).where(TurnoverTicket.id == ticket_id)
    if lock:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def get_repair(db: Session, repair_id: int, *, lock: bool = False) -> Optional[RepairRequest]:
    stmt = select(RepairRequest).where(RepairRequest.id == repair_id)
    if lock:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def active_tickets_for_room(db: Session, room_id: int) -> list[TurnoverTicket]:
    return list(db.scalars(select(TurnoverTicket).where(
        TurnoverTicket.room_id == room_id, TurnoverTicket.is_active.is_(True))).all())


def search_tickets(db: Session, *, search: Optional[str], status: Optional[list[TicketStatus]], priority: Optional[Priority],
                   housekeeper_id: Optional[int], room_id: Optional[int], active_only: bool,
                   created_from: Optional[date], created_to: Optional[date], page: int, page_size: int):
    stmt = select(TurnoverTicket).join(Room, Room.id == TurnoverTicket.room_id)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(Room.room_number.ilike(like), TurnoverTicket.ticket_number.ilike(like)))
    if status:
        stmt = stmt.where(TurnoverTicket.status.in_(status))
    if priority:
        stmt = stmt.where(TurnoverTicket.priority == priority)
    if housekeeper_id:
        stmt = stmt.where(TurnoverTicket.assigned_housekeeper_id == housekeeper_id)
    if room_id:
        stmt = stmt.where(TurnoverTicket.room_id == room_id)
    if active_only:
        stmt = stmt.where(TurnoverTicket.is_active.is_(True))
    if created_from:
        stmt = stmt.where(TurnoverTicket.created_at >= datetime.combine(created_from, time.min))
    if created_to:
        stmt = stmt.where(TurnoverTicket.created_at < datetime.combine(created_to + timedelta(days=1), time.min))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(TurnoverTicket.created_at.desc(), TurnoverTicket.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).unique().all()
    return list(rows), total


def search_repairs(db: Session, *, statuses: Optional[list[RepairStatus]], engineer_id: Optional[int],
                   include_unassigned: bool, search: Optional[str], page: int, page_size: int):
    stmt = select(RepairRequest).join(Room, Room.id == RepairRequest.room_id)
    if statuses:
        stmt = stmt.where(RepairRequest.status.in_(statuses))
    if engineer_id is not None:
        cond = RepairRequest.assigned_engineer_id == engineer_id
        if include_unassigned:
            cond = or_(cond, (RepairRequest.assigned_engineer_id.is_(None)) & (RepairRequest.status.in_(list(OPEN_REPAIR_STATUSES))))
        stmt = stmt.where(cond)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(Room.room_number.ilike(like), RepairRequest.repair_number.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(RepairRequest.created_at.desc(), RepairRequest.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).unique().all()
    return list(rows), total


def repairs_for_room(db: Session, room_id: int, exclude_id: Optional[int] = None, limit: int = 20) -> list[RepairRequest]:
    stmt = select(RepairRequest).where(RepairRequest.room_id == room_id)
    if exclude_id:
        stmt = stmt.where(RepairRequest.id != exclude_id)
    return list(db.scalars(stmt.order_by(RepairRequest.id.desc()).limit(limit)).unique().all())
