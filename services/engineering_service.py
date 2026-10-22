from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from core.exceptions import ForbiddenError, NotFoundError, ValidationFailedError, WorkflowError
from database.base import utcnow
from models.enums import (
    OPEN_REPAIR_STATUSES, TERMINAL_TICKET_STATUSES, Department, ItemResult, OccupancyStatus, OperationalStatus, Role,
    Priority, RepairStatus, SessionKind, SessionOutcome, SessionStatus, TicketStatus,
)
from models.repair import RepairRequest
from models.room import Room
from models.turnover import TicketAssignment, TurnoverTicket
from models.user import User
from repositories import room_repository, turnover_repository
from schemas.inspection_schema import ResultUpdate
from schemas.turnover_schema import TicketCreate
from services import audit_service
from services import turnover_service as wf

ENGINEERING_ROOM_STATUSES = {OperationalStatus.ENGINEERING_REQUIRED, OperationalStatus.ENGINEERING_ASSIGNED,
                             OperationalStatus.ENGINEERING_IN_PROGRESS}

SCOPES = {
    "new": [RepairStatus.NEW],
    "assigned": [RepairStatus.ASSIGNED],
    "in_progress": [RepairStatus.IN_PROGRESS],
    "completed": [RepairStatus.COMPLETED],
    "reopened": [RepairStatus.REOPENED],
    "open": list(OPEN_REPAIR_STATUSES),
}


def get_repair(db: Session, repair_id: int, *, lock: bool = False) -> RepairRequest:
    r = turnover_repository.get_repair(db, repair_id, lock=lock)
    if not r:
        raise NotFoundError("Repair request not found.")
    return r


def ensure_can_view(user: User, repair: RepairRequest) -> None:
    if user.department in (Department.FRONT_DESK, Department.ENGINEERING):
        return
    if user.department == Department.HOUSEKEEPING and repair.ticket is not None and wf.can_view_ticket(user, repair.ticket):
        return
    raise ForbiddenError("You do not have access to this repair request.")


# --------------------------------------------------------------------------- room status for direct repairs

def sync_room_for_direct_repairs(db: Session, room: Room) -> None:
    """Room status while front-desk repairs (not part of a turnover) are open.
    A turnover ticket, when present, controls the room instead."""
    if room.active_ticket_id:
        return
    db.flush()
    open_direct = list(db.scalars(select(RepairRequest).where(
        RepairRequest.room_id == room.id, RepairRequest.ticket_id.is_(None),
        RepairRequest.status.in_(list(OPEN_REPAIR_STATUSES)))).unique().all())
    blocking = [r for r in open_direct if r.blocks_room]
    if blocking:
        if any(r.status == RepairStatus.IN_PROGRESS for r in blocking):
            room.operational_status = OperationalStatus.ENGINEERING_IN_PROGRESS
        elif any(r.assigned_engineer_id for r in blocking):
            room.operational_status = OperationalStatus.ENGINEERING_ASSIGNED
        else:
            room.operational_status = OperationalStatus.ENGINEERING_REQUIRED
    elif room.operational_status in ENGINEERING_ROOM_STATUSES:
        room.operational_status = OperationalStatus.READY_FOR_GUEST
        room.last_ready_at = utcnow()
    room.assigned_engineer_id = next((r.assigned_engineer_id for r in open_direct if r.assigned_engineer_id), None)


def _after_change(db: Session, repair: RepairRequest, actor: User, action: str, message: str,
                  details: Optional[dict] = None) -> None:
    ticket = repair.ticket
    if ticket is not None:
        wf.transition(db, ticket, wf.engineering_status_for(ticket), actor=actor, action=action, repair=repair,
                      message=message, details=details)
    else:
        previous = repair.room.operational_status
        sync_room_for_direct_repairs(db, repair.room)
        audit_service.log(db, actor=actor, action=action, message=message, entity_type="repair", entity_id=repair.id,
                          repair_id=repair.id, room_id=repair.room_id, from_status=previous,
                          to_status=repair.room.operational_status, details=details)


# --------------------------------------------------------------------------- front desk raises a repair

def create_direct(db: Session, actor: User, *, room_id: int, reported_defect: str, priority: Priority,
                  engineer_id: Optional[int]) -> RepairRequest:
    room = room_repository.get(db, room_id, lock=True)
    if not room or not room.is_active:
        raise NotFoundError("Room not found or inactive.")
    defect = reported_defect.strip()
    if len(defect) < 3:
        raise ValidationFailedError("Describe the problem.", code="DEFECT_REQUIRED")
    engineer = wf.get_active_user(db, engineer_id, Department.ENGINEERING, "engineer") if engineer_id else None
    ticket = room.active_ticket if room.active_ticket_id else None
    blocks = (ticket is None and room.occupancy_status == OccupancyStatus.VACANT
              and room.operational_status == OperationalStatus.READY_FOR_GUEST)
    repair = RepairRequest(
        room_id=room.id, status=RepairStatus.NEW, priority=priority, reported_defect=defect[:5000],
        created_by_id=actor.id, blocks_room=blocks,
    )
    if ticket is not None:
        repair.ticket = ticket
    db.add(repair)
    db.flush()
    repair.repair_number = f"RR-{utcnow():%Y%m%d}-{repair.id:05d}"
    if engineer:
        repair.assigned_engineer_id = engineer.id
        repair.assigned_engineer = engineer
        repair.status = RepairStatus.ASSIGNED
        db.add(TicketAssignment(ticket_id=ticket.id if ticket else None, repair_id=repair.id,
                                department=Department.ENGINEERING, assignee_id=engineer.id,
                                assigned_by_id=actor.id, assigned_at=utcnow()))
    where = ("added to the open turnover" if ticket is not None else
             "room blocked from sale until fixed" if blocks else
             "guest in room" if room.occupancy_status == OccupancyStatus.OCCUPIED else "room status unchanged")
    msg = f"Front desk raised repair {repair.repair_number} for room {room.room_number} ({where})"
    if engineer:
        msg += f", assigned to {engineer.display_name}"
    _after_change(db, repair, actor, "REPAIR_RAISED", msg, details={"defect": defect[:500]})
    db.commit()
    db.refresh(repair)
    return repair


def list_for_engineer(db: Session, user: User, scope: Optional[str], search: Optional[str], page: int, page_size: int):
    """Scopes: new (unassigned, team-wide), assigned, in_progress, awaiting_verification, completed, reopened,
    open, or all (default: mine plus unassigned)."""
    stmt = select(RepairRequest).join(Room, Room.id == RepairRequest.room_id).outerjoin(
        TurnoverTicket, TurnoverTicket.id == RepairRequest.ticket_id)
    if scope == "new":
        stmt = stmt.where(RepairRequest.assigned_engineer_id.is_(None),
                          RepairRequest.status.in_(list(OPEN_REPAIR_STATUSES)))
    elif scope == "awaiting_verification":
        stmt = stmt.where(RepairRequest.assigned_engineer_id == user.id, RepairRequest.status == RepairStatus.COMPLETED,
                          TurnoverTicket.is_active.is_(True))
    elif scope in SCOPES:
        stmt = stmt.where(RepairRequest.assigned_engineer_id == user.id, RepairRequest.status.in_(SCOPES[scope]))
    else:
        stmt = stmt.where(or_(RepairRequest.assigned_engineer_id == user.id,
                              and_(RepairRequest.assigned_engineer_id.is_(None),
                                   RepairRequest.status.in_(list(OPEN_REPAIR_STATUSES)))))
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(Room.room_number.ilike(like), RepairRequest.repair_number.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(RepairRequest.updated_at.desc(), RepairRequest.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).unique().all()
    return list(rows), total


def list_all(db: Session, statuses, engineer_id, search, page, page_size):
    return turnover_repository.search_repairs(db, statuses=statuses, engineer_id=engineer_id, include_unassigned=False,
                                              search=search, page=page, page_size=page_size)


def assign(db: Session, actor: User, repair_id: int, engineer_id: int, reason: Optional[str]) -> RepairRequest:
    repair = get_repair(db, repair_id, lock=True)
    ticket = repair.ticket
    if repair.status not in OPEN_REPAIR_STATUSES:
        raise WorkflowError(f"A {repair.status.value.lower()} repair cannot be assigned.")
    if ticket is not None and ticket.status in TERMINAL_TICKET_STATUSES:
        raise WorkflowError("The turnover ticket is closed.")
    supervisor = actor.role in (Role.ADMIN, Role.ENG_SUPERVISOR)
    if not supervisor and actor.department == Department.ENGINEERING:
        if engineer_id != actor.id:
            raise ForbiddenError("Engineers can only assign repairs to themselves.", code="SELF_ASSIGN_ONLY")
        if repair.assigned_engineer_id not in (None, actor.id):
            raise ForbiddenError("This repair is already assigned to another engineer.", code="NOT_ASSIGNEE")
    elif not supervisor:
        raise ForbiddenError("You cannot assign repairs.")
    if repair.status == RepairStatus.IN_PROGRESS and not supervisor:
        raise WorkflowError("Repair is in progress.")
    engineer = wf.get_active_user(db, engineer_id, Department.ENGINEERING, "engineer")
    if repair.assigned_engineer_id == engineer.id and repair.status != RepairStatus.NEW:
        return repair
    previous = repair.assigned_engineer
    repair.assigned_engineer_id = engineer.id
    repair.assigned_engineer = engineer
    if repair.status == RepairStatus.NEW:
        repair.status = RepairStatus.ASSIGNED
    db.add(TicketAssignment(ticket_id=ticket.id if ticket else None, repair_id=repair.id,
                            department=Department.ENGINEERING, assignee_id=engineer.id,
                            previous_assignee_id=previous.id if previous else None,
                            assigned_by_id=actor.id, reason=reason, assigned_at=utcnow()))
    msg = (f"{engineer.display_name} claimed repair {repair.repair_number}" if actor.id == engineer.id
           else f"Repair {repair.repair_number} {'reassigned' if previous else 'assigned'} to {engineer.display_name}")
    _after_change(db, repair, actor, "REPAIR_ASSIGNED", msg, details={"reason": reason} if reason else None)
    db.commit()
    db.refresh(repair)
    return repair


def _ensure_assignee(user: User, repair: RepairRequest) -> None:
    if user.department != Department.ENGINEERING or repair.assigned_engineer_id != user.id:
        raise ForbiddenError("This repair is assigned to another engineer.", code="NOT_ASSIGNEE")


def start(db: Session, user: User, repair_id: int) -> RepairRequest:
    repair = get_repair(db, repair_id, lock=True)
    _ensure_assignee(user, repair)
    if repair.status not in (RepairStatus.ASSIGNED, RepairStatus.REOPENED):
        raise WorkflowError(f"Only assigned or reopened repairs can be started (current: {repair.status.value}).")
    ticket = repair.ticket
    if ticket is not None and (ticket.status in TERMINAL_TICKET_STATUSES
                               or ticket.status == TicketStatus.HOUSEKEEPING_IN_PROGRESS):
        raise WorkflowError(f"The turnover ticket is {ticket.status.value.lower()}; repair work cannot start now.")
    wf.start_session(db, ticket, kind=SessionKind.ENGINEERING, inspector=user, repair=repair)
    repair.status = RepairStatus.IN_PROGRESS
    repair.started_at = repair.started_at or utcnow()
    _after_change(db, repair, user, "REPAIR_STARTED", f"{user.display_name} started repair {repair.repair_number}")
    db.commit()
    db.refresh(repair)
    return repair


def current_session(repair: RepairRequest):
    sessions = [s for s in repair.sessions if s.status != SessionStatus.SUPERSEDED]
    return sessions[-1] if sessions else None


def _open_session(user: User, repair: RepairRequest):
    _ensure_assignee(user, repair)
    if repair.status != RepairStatus.IN_PROGRESS:
        raise WorkflowError("Start the repair before recording checklist results.", code="NOT_STARTED")
    session = current_session(repair)
    if not session or session.status != SessionStatus.IN_PROGRESS:
        raise WorkflowError("There is no open engineering inspection on this repair.", code="SESSION_CLOSED")
    return session


def save_checklist(db: Session, user: User, repair_id: int, items: list[ResultUpdate],
                   diagnosis: Optional[str], repair_notes: Optional[str]) -> RepairRequest:
    repair = get_repair(db, repair_id, lock=True)
    session = _open_session(user, repair)
    wf.save_results(db, session, user, items)
    if diagnosis is not None:
        repair.diagnosis = diagnosis.strip() or None
    if repair_notes is not None:
        repair.repair_notes = repair_notes.strip() or None
    db.commit()
    db.refresh(repair)
    return repair


def complete(db: Session, user: User, repair_id: int, *, requires_recleaning: bool,
             diagnosis: Optional[str], repair_notes: Optional[str]) -> RepairRequest:
    repair = get_repair(db, repair_id, lock=True)
    session = _open_session(user, repair)
    if diagnosis is not None:
        repair.diagnosis = diagnosis.strip() or None
    if repair_notes is not None:
        repair.repair_notes = repair_notes.strip() or None
    problems = wf.validate_for_submit(session)
    failed = [r for r in session.results if r.result == ItemResult.FAIL]
    if failed:
        problems.append("These checks failed, so the repair stays open: " + ", ".join(r.item_name for r in failed) + ".")
    if not repair.diagnosis:
        problems.append("Add a diagnosis.")
    if not repair.repair_notes:
        problems.append("Add repair notes describing the work done.")
    if problems:
        db.commit()  # keep notes the engineer typed
        raise ValidationFailedError("The repair cannot be completed yet.", code="REPAIR_INCOMPLETE", details=problems)

    now = utcnow()
    session.status = SessionStatus.SUBMITTED
    session.outcome = SessionOutcome.PASS
    session.submitted_at = now
    session.submitted_by_id = user.id
    repair.status = RepairStatus.COMPLETED
    repair.completed_at = now
    repair.completed_by_id = user.id
    repair.requires_recleaning = requires_recleaning
    ticket = repair.ticket
    room = repair.room
    open_turnover_for_reclean = False
    msg = f"Repair {repair.repair_number} completed by {user.display_name}"
    if ticket is not None:
        if requires_recleaning:
            ticket.needs_reclean = True
            msg += "; room returned to Housekeeping for re-cleaning"
    elif requires_recleaning:
        if room.occupancy_status == OccupancyStatus.VACANT and room.operational_status != OperationalStatus.OUT_OF_SERVICE:
            open_turnover_for_reclean = True
            msg += "; housekeeping turnover opened for re-cleaning"
        else:
            msg += "; re-cleaning requested (guest in room, arrange with the front desk)"
    _after_change(db, repair, user, "REPAIR_COMPLETED", msg, details={"requires_recleaning": requires_recleaning})
    db.commit()
    if open_turnover_for_reclean:
        db.refresh(room)
        if not room.active_ticket_id and room.operational_status != OperationalStatus.OUT_OF_SERVICE:
            wf.create_ticket(db, user, TicketCreate(room_id=room.id, priority=repair.priority,
                                                    notes=f"Re-clean after repair {repair.repair_number}"),
                             message=f"Turnover opened for room {room.room_number}: re-clean after repair {repair.repair_number}")
    db.refresh(repair)
    return repair


def reopen(db: Session, user: User, repair_id: int, reason: str) -> RepairRequest:
    repair = get_repair(db, repair_id, lock=True)
    if (user.role == Role.TECHNICIAN and repair.assigned_engineer_id not in (None, user.id)):
        raise ForbiddenError("Only the assigned engineer or the front desk can reopen this repair.")
    if user.department not in (Department.ENGINEERING, Department.FRONT_DESK):
        raise ForbiddenError("You cannot reopen repairs.")
    if repair.status != RepairStatus.COMPLETED:
        raise WorkflowError("Only completed repairs can be reopened.")
    ticket = repair.ticket
    room = repair.room
    if ticket is None and room.active_ticket_id:
        # The room has entered a turnover since: the reopened repair joins it.
        ticket = room.active_ticket
        repair.ticket = ticket
        repair.blocks_room = False
        for sess in repair.sessions:
            sess.ticket_id = ticket.id
    if ticket is not None:
        if ticket.status in TERMINAL_TICKET_STATUSES:
            raise WorkflowError("The turnover ticket is closed. Open a new turnover ticket or raise a new repair.")
        if ticket.status == TicketStatus.HOUSEKEEPING_IN_PROGRESS:
            raise WorkflowError("Housekeeping is working in the room. Reopen after they submit.")
    else:
        repair.blocks_room = (room.occupancy_status == OccupancyStatus.VACANT
                              and room.operational_status == OperationalStatus.READY_FOR_GUEST)
    repair.status = RepairStatus.REOPENED
    repair.reopen_count += 1
    repair.last_reopen_reason = reason
    repair.completed_at = None
    _after_change(db, repair, user, "REPAIR_REOPENED", f"Repair {repair.repair_number} reopened", details={"reason": reason})
    db.commit()
    db.refresh(repair)
    return repair


def room_history(db: Session, repair: RepairRequest) -> list[RepairRequest]:
    return turnover_repository.repairs_for_room(db, repair.room_id, exclude_id=repair.id)
