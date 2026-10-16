from sqlalchemy import select
from sqlalchemy.orm import Session

from core.exceptions import ConflictError, NotFoundError, ValidationFailedError, WorkflowError
from database.base import utcnow
from models.audit import ActivityLog
from models.enums import OccupancyStatus, OperationalStatus
from models.room import Room, RoomType
from models.turnover import TurnoverTicket
from repositories import room_repository
from schemas.room_schema import RoomCreate, RoomOccupancyUpdate, RoomStatusOverride, RoomTypeCreate, RoomTypeUpdate, RoomUpdate
from services import audit_service


def get_room(db: Session, room_id: int) -> Room:
    room = room_repository.get(db, room_id)
    if not room:
        raise NotFoundError("Room not found.")
    return room


def _room_type(db: Session, room_type_id: int) -> RoomType:
    rt = db.get(RoomType, room_type_id)
    if not rt:
        raise ValidationFailedError("Room type does not exist.", code="INVALID_ROOM_TYPE")
    return rt


def create_room(db: Session, actor, data: RoomCreate) -> Room:
    if room_repository.get_by_number(db, data.room_number):
        raise ConflictError(f"Room {data.room_number} already exists.", code="ROOM_EXISTS")
    _room_type(db, data.room_type_id)
    room = Room(
        room_number=data.room_number.strip(),
        floor=data.floor,
        room_type_id=data.room_type_id,
        occupancy_status=data.occupancy_status,
        operational_status=data.operational_status,
        notes=data.notes,
        last_ready_at=utcnow() if data.operational_status == OperationalStatus.READY_FOR_GUEST else None,
    )
    db.add(room)
    db.flush()
    audit_service.log(db, actor=actor, action="ROOM_CREATED", entity_type="room", entity_id=room.id, room_id=room.id,
                      message=f"Created room {room.room_number}")
    db.commit()
    return room


def update_room(db: Session, actor, room_id: int, data: RoomUpdate) -> Room:
    room = get_room(db, room_id)
    changes = {}
    if data.room_number is not None and data.room_number != room.room_number:
        other = room_repository.get_by_number(db, data.room_number)
        if other and other.id != room.id:
            raise ConflictError(f"Room {data.room_number} already exists.", code="ROOM_EXISTS")
        changes["room_number"] = [room.room_number, data.room_number]
        room.room_number = data.room_number.strip()
    if data.floor is not None and data.floor != room.floor:
        changes["floor"] = [room.floor, data.floor]
        room.floor = data.floor
    if data.room_type_id is not None and data.room_type_id != room.room_type_id:
        _room_type(db, data.room_type_id)
        changes["room_type_id"] = [room.room_type_id, data.room_type_id]
        room.room_type_id = data.room_type_id
    if data.notes is not None and data.notes != room.notes:
        changes["notes"] = "updated"
        room.notes = data.notes
    if data.is_active is not None and data.is_active != room.is_active:
        if not data.is_active and room.active_ticket_id:
            raise WorkflowError("Close or cancel the open turnover ticket before deactivating this room.")
        changes["is_active"] = [room.is_active, data.is_active]
        room.is_active = data.is_active
    if changes:
        audit_service.log(db, actor=actor, action="ROOM_UPDATED", entity_type="room", entity_id=room.id, room_id=room.id,
                          message=f"Updated room {room.room_number}", details=changes)
        db.commit()
        db.refresh(room)
    return room


def override_status(db: Session, actor, room_id: int, data: RoomStatusOverride) -> Room:
    room = room_repository.get(db, room_id, lock=True)
    if not room:
        raise NotFoundError("Room not found.")
    if room.active_ticket_id:
        raise WorkflowError(
            "This room has an open turnover ticket. Its status follows the ticket workflow; "
            "cancel the ticket to take the room out of the workflow.", code="ROOM_IN_WORKFLOW")
    allowed = {OperationalStatus.OUT_OF_SERVICE, OperationalStatus.READY_FOR_GUEST, OperationalStatus.AWAITING_HOUSEKEEPING}
    if data.operational_status not in allowed:
        raise WorkflowError("Without a ticket a room can only be set to Out of Service, Awaiting Housekeeping, or Ready for Guest.")
    previous = room.operational_status
    room.operational_status = data.operational_status
    if data.operational_status == OperationalStatus.READY_FOR_GUEST:
        room.last_ready_at = utcnow()
    audit_service.log(db, actor=actor, action="ROOM_STATUS_OVERRIDE", entity_type="room", entity_id=room.id,
                      room_id=room.id, from_status=previous, to_status=room.operational_status,
                      message=f"Room {room.room_number} status set to {room.operational_status.value} by administrator",
                      details={"reason": data.reason})
    db.commit()
    return room


def set_occupancy(db: Session, actor, room_id: int, data: RoomOccupancyUpdate) -> Room:
    room = room_repository.get(db, room_id, lock=True)
    if not room:
        raise NotFoundError("Room not found.")
    if data.occupancy_status == room.occupancy_status:
        return room
    if data.occupancy_status == OccupancyStatus.OCCUPIED and room.operational_status != OperationalStatus.READY_FOR_GUEST:
        raise WorkflowError("Only rooms that are Ready for Guest can be checked in.", code="ROOM_NOT_READY")
    previous = room.occupancy_status
    room.occupancy_status = data.occupancy_status
    audit_service.log(db, actor=actor, action="ROOM_OCCUPANCY_CHANGED", entity_type="room", entity_id=room.id,
                      room_id=room.id, from_status=previous, to_status=room.occupancy_status,
                      message=f"Room {room.room_number} marked {room.occupancy_status.value.lower()}",
                      details={"reason": data.reason} if data.reason else None)
    db.commit()
    return room


def history(db: Session, room_id: int):
    room = get_room(db, room_id)
    tickets = list(db.scalars(select(TurnoverTicket).where(TurnoverTicket.room_id == room.id)
                              .order_by(TurnoverTicket.id.desc()).limit(50)).unique().all())
    logs = list(db.scalars(select(ActivityLog).where(ActivityLog.room_id == room.id)
                           .order_by(ActivityLog.id.desc()).limit(200)).all())
    return room, tickets, logs


# ---- room types ----

def create_room_type(db: Session, actor, data: RoomTypeCreate) -> RoomType:
    if db.scalar(select(RoomType).where(RoomType.name == data.name.strip())):
        raise ConflictError("A room type with that name exists.", code="ROOM_TYPE_EXISTS")
    rt = RoomType(name=data.name.strip(), category=data.category, description=data.description, is_active=data.is_active)
    db.add(rt)
    db.flush()
    audit_service.log(db, actor=actor, action="ROOM_TYPE_CREATED", entity_type="room_type", entity_id=rt.id,
                      message=f"Created room type {rt.name}")
    db.commit()
    return rt


def update_room_type(db: Session, actor, type_id: int, data: RoomTypeUpdate) -> RoomType:
    rt = db.get(RoomType, type_id)
    if not rt:
        raise NotFoundError("Room type not found.")
    if data.name and data.name.strip() != rt.name:
        if db.scalar(select(RoomType).where(RoomType.name == data.name.strip(), RoomType.id != rt.id)):
            raise ConflictError("A room type with that name exists.", code="ROOM_TYPE_EXISTS")
        rt.name = data.name.strip()
    for field in ("category", "description", "is_active"):
        value = getattr(data, field)
        if value is not None:
            setattr(rt, field, value)
    audit_service.log(db, actor=actor, action="ROOM_TYPE_UPDATED", entity_type="room_type", entity_id=rt.id,
                      message=f"Updated room type {rt.name}")
    db.commit()
    return rt
