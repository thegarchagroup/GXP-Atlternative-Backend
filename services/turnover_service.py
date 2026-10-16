"""Turnover ticket lifecycle and shared workflow rules.

The ticket status is the single source of truth for where a room is in the
turnover process; the room's operational status is derived from it.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import settings
from core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationFailedError, WorkflowError
from database.base import utcnow
from models.audit import ActivityLog
from models.enums import (
    OPEN_REPAIR_STATUSES, TERMINAL_TICKET_STATUSES, ChecklistType, Department, ItemResult, OccupancyStatus,
    OperationalStatus, RepairStatus, SessionKind, SessionOutcome, SessionStatus, TicketStatus,
)
from models.inspection import Attachment, InspectionResult, InspectionSession
from models.repair import RepairRequest
from models.turnover import TicketAssignment, TurnoverTicket
from models.user import User
from repositories import checklist_repository, room_repository, turnover_repository
from schemas.inspection_schema import ResultUpdate
from schemas.turnover_schema import TicketCreate
from services import audit_service

TICKET_TO_ROOM = {
    TicketStatus.AWAITING_HOUSEKEEPING: OperationalStatus.AWAITING_HOUSEKEEPING,
    TicketStatus.HOUSEKEEPING_ASSIGNED: OperationalStatus.HOUSEKEEPING_ASSIGNED,
    TicketStatus.HOUSEKEEPING_IN_PROGRESS: OperationalStatus.HOUSEKEEPING_IN_PROGRESS,
    TicketStatus.ENGINEERING_REQUIRED: OperationalStatus.ENGINEERING_REQUIRED,
    TicketStatus.ENGINEERING_ASSIGNED: OperationalStatus.ENGINEERING_ASSIGNED,
    TicketStatus.ENGINEERING_IN_PROGRESS: OperationalStatus.ENGINEERING_IN_PROGRESS,
    TicketStatus.AWAITING_FINAL_VERIFICATION: OperationalStatus.AWAITING_FINAL_VERIFICATION,
}

HOUSEKEEPING_TYPES = [ChecklistType.HOUSEKEEPING_CLEANING, ChecklistType.HOUSEKEEPING_INSPECTION]
ENGINEERING_TYPES = [ChecklistType.ENGINEERING_INSPECTION]


# --------------------------------------------------------------------------- lookups

def get_ticket(db: Session, ticket_id: int, *, lock: bool = False) -> TurnoverTicket:
    t = turnover_repository.get_ticket(db, ticket_id, lock=lock)
    if not t:
        raise NotFoundError("Turnover ticket not found.")
    return t


def get_active_user(db: Session, pk: int, department: Department, label: str) -> User:
    user = db.get(User, pk)
    if not user or user.is_deleted or not user.is_active:
        raise ValidationFailedError(f"The selected {label} is not an active user.", code="INVALID_ASSIGNEE")
    if user.department != department:
        raise ValidationFailedError(f"The selected user is not in {department.value.replace('_', ' ').title()}.",
                                    code="INVALID_ASSIGNEE")
    return user


def can_view_ticket(user: User, ticket: TurnoverTicket) -> bool:
    if user.department == Department.FRONT_DESK:
        return True
    if user.department == Department.HOUSEKEEPING:
        return ticket.assigned_housekeeper_id == user.id or any(
            s.inspector_id == user.id for s in ticket.sessions if s.kind == SessionKind.HOUSEKEEPING)
    if user.department == Department.ENGINEERING:
        return len(ticket.repairs) > 0
    return False


def ensure_can_view(user: User, ticket: TurnoverTicket) -> None:
    if not can_view_ticket(user, ticket):
        raise ForbiddenError("You do not have access to this ticket.")


# --------------------------------------------------------------------------- status handling

def sync_room(ticket: TurnoverTicket) -> None:
    room = ticket.room
    if room.active_ticket_id != ticket.id or ticket.status in TERMINAL_TICKET_STATUSES:
        return
    if ticket.status == TicketStatus.RECLEAN_REQUIRED:
        room.operational_status = (OperationalStatus.HOUSEKEEPING_ASSIGNED if ticket.assigned_housekeeper_id
                                   else OperationalStatus.AWAITING_HOUSEKEEPING)
    else:
        room.operational_status = TICKET_TO_ROOM[ticket.status]
    room.assigned_housekeeper_id = ticket.assigned_housekeeper_id
    open_repairs = [r for r in ticket.repairs if r.status in OPEN_REPAIR_STATUSES]
    room.assigned_engineer_id = next((r.assigned_engineer_id for r in open_repairs if r.assigned_engineer_id), None)


def transition(db: Session, ticket: TurnoverTicket, new_status: TicketStatus, *, actor: User, action: str,
               message: str, repair: Optional[RepairRequest] = None, details: Optional[dict] = None) -> None:
    previous = ticket.status
    ticket.status = new_status
    sync_room(ticket)
    audit_service.log(db, actor=actor, action=action, message=message, entity_type="ticket", entity_id=ticket.id,
                      ticket_id=ticket.id, repair_id=repair.id if repair else None, room_id=ticket.room_id,
                      from_status=previous, to_status=new_status, details=details)


HOUSEKEEPING_STAGE = {TicketStatus.AWAITING_HOUSEKEEPING, TicketStatus.HOUSEKEEPING_ASSIGNED,
                      TicketStatus.HOUSEKEEPING_IN_PROGRESS}


def engineering_status_for(ticket: TurnoverTicket) -> TicketStatus:
    """Status after an engineering action. A ticket still waiting for (or in) housekeeping
    stays there: housekeeping's submission moves it on and picks up any open repairs."""
    if ticket.status in HOUSEKEEPING_STAGE:
        return ticket.status
    return derive_post_housekeeping_status(ticket)


def derive_post_housekeeping_status(ticket: TurnoverTicket) -> TicketStatus:
    open_repairs = [r for r in ticket.repairs if r.status in OPEN_REPAIR_STATUSES]
    if open_repairs:
        if any(r.status == RepairStatus.IN_PROGRESS for r in open_repairs):
            return TicketStatus.ENGINEERING_IN_PROGRESS
        if any(r.assigned_engineer_id for r in open_repairs):
            return TicketStatus.ENGINEERING_ASSIGNED
        return TicketStatus.ENGINEERING_REQUIRED
    if ticket.needs_reclean:
        return TicketStatus.RECLEAN_REQUIRED
    return TicketStatus.AWAITING_FINAL_VERIFICATION


# --------------------------------------------------------------------------- inspection sessions

def start_session(db: Session, ticket: Optional[TurnoverTicket], *, kind: SessionKind, inspector: User,
                  repair: Optional[RepairRequest] = None, is_reclean: bool = False) -> InspectionSession:
    types = HOUSEKEEPING_TYPES if kind == SessionKind.HOUSEKEEPING else ENGINEERING_TYPES
    room = ticket.room if ticket is not None else repair.room
    items = checklist_repository.active_items_for(db, types, room.room_type_id)
    if not items:
        label = "housekeeping" if kind == SessionKind.HOUSEKEEPING else "engineering"
        raise WorkflowError(f"No active {label} checklist items apply to this room type. "
                            "Ask the administrator to configure the checklist.", code="NO_CHECKLIST")
    if repair is not None:
        previous = list(repair.sessions)
    else:
        previous = [s for s in ticket.sessions if s.kind == SessionKind.HOUSEKEEPING]
    for s in previous:
        if s.status == SessionStatus.IN_PROGRESS:
            s.status = SessionStatus.SUPERSEDED
    session = InspectionSession(
        ticket_id=ticket.id if ticket is not None else None, repair_id=repair.id if repair else None, kind=kind,
        round_number=len(previous) + 1, is_reclean=is_reclean, status=SessionStatus.IN_PROGRESS,
        inspector_id=inspector.id, started_at=utcnow(),
    )
    if ticket is not None:
        session.ticket = ticket
    db.add(session)
    for template, item in items:
        db.add(InspectionResult(
            session=session, template_item_id=item.id, checklist_type=template.checklist_type,
            item_name=item.name, description=item.description, category=item.category,
            is_mandatory=item.is_mandatory, allow_not_applicable=item.allow_not_applicable,
            display_order=item.display_order, reference_instructions=item.reference_instructions,
            result=ItemResult.PENDING,
        ))
    db.flush()
    if repair is not None:
        db.expire(repair, ["sessions"])
    return session


def current_session(ticket: TurnoverTicket, *, repair_id: Optional[int] = None,
                    kind: SessionKind = SessionKind.HOUSEKEEPING) -> Optional[InspectionSession]:
    if repair_id is not None:
        sessions = [s for s in ticket.sessions if s.repair_id == repair_id]
    else:
        sessions = [s for s in ticket.sessions if s.kind == kind and s.repair_id is None]
    sessions = [s for s in sessions if s.status != SessionStatus.SUPERSEDED]
    return sessions[-1] if sessions else None


def save_results(db: Session, session: InspectionSession, actor: User, updates: list[ResultUpdate]) -> None:
    if session.status != SessionStatus.IN_PROGRESS:
        raise WorkflowError("This inspection has already been submitted.", code="SESSION_CLOSED")
    by_id = {r.id: r for r in session.results}
    now = utcnow()
    for u in updates:
        r = by_id.get(u.result_id)
        if r is None:
            raise ValidationFailedError(f"Checklist item {u.result_id} is not part of this inspection.")
        if u.result == ItemResult.NOT_APPLICABLE and not r.allow_not_applicable:
            raise ValidationFailedError(f"'{r.item_name}' cannot be marked Not Applicable.", code="NA_NOT_ALLOWED")
        if r.checklist_type == ChecklistType.HOUSEKEEPING_CLEANING and u.result == ItemResult.FAIL:
            raise ValidationFailedError(f"Cleaning task '{r.item_name}' is either done or not applicable. "
                                        "Report defects in the inspection checklist.", code="INVALID_RESULT")
        remarks = (u.remarks or "").strip() or None
        changed = r.result != u.result or r.remarks != remarks
        r.result = u.result
        r.remarks = remarks
        if changed:
            r.inspector_id = actor.id if u.result != ItemResult.PENDING else None
            r.inspected_at = now if u.result != ItemResult.PENDING else None
        if u.attachment_ids is not None:
            _link_attachments(db, session, r, actor, u.attachment_ids)


def _link_attachments(db: Session, session: InspectionSession, result: InspectionResult, actor: User, ids: list[int]):
    wanted = set(ids)
    for att in list(result.attachments):
        if att.id not in wanted:
            att.inspection_result_id = None
    for aid in wanted:
        att = db.get(Attachment, aid)
        if att is None:
            raise ValidationFailedError(f"Attachment {aid} not found.")
        if att.uploaded_by_id != actor.id and att.ticket_id != session.ticket_id:
            raise ForbiddenError("You can only attach your own uploads.")
        if att.ticket_id not in (None, session.ticket_id):
            raise ValidationFailedError("That attachment belongs to another ticket.")
        att.ticket_id = session.ticket_id
        att.repair_id = session.repair_id or att.repair_id
        att.inspection_result_id = result.id
    db.flush()
    db.expire(result, ["attachments"])


def validate_for_submit(session: InspectionSession) -> list[str]:
    problems = []
    for r in session.results:
        if r.is_mandatory and r.result == ItemResult.PENDING:
            problems.append(f"'{r.item_name}' is required.")
        if r.result == ItemResult.FAIL and not (r.remarks or "").strip():
            problems.append(f"'{r.item_name}' failed and needs a remark describing the issue.")
    return problems


# --------------------------------------------------------------------------- tickets

def _assign_housekeeper(db: Session, ticket: TurnoverTicket, assignee: User, actor: User, reason: Optional[str]) -> None:
    previous = ticket.assigned_housekeeper_id
    ticket.assigned_housekeeper_id = assignee.id
    ticket.assigned_housekeeper = assignee
    db.add(TicketAssignment(ticket_id=ticket.id, department=Department.HOUSEKEEPING, assignee_id=assignee.id,
                            previous_assignee_id=previous, assigned_by_id=actor.id, reason=reason, assigned_at=utcnow()))


def create_ticket(db: Session, actor: User, data: TicketCreate, message: Optional[str] = None) -> TurnoverTicket:
    room = room_repository.get(db, data.room_id, lock=True)
    if not room or not room.is_active:
        raise NotFoundError("Room not found or inactive.")
    if room.operational_status == OperationalStatus.OUT_OF_SERVICE:
        raise WorkflowError("Room is out of service. Return it to service before starting a turnover.",
                            code="ROOM_OUT_OF_SERVICE")
    existing = turnover_repository.active_tickets_for_room(db, room.id)
    if existing and not data.allow_duplicate:
        raise ConflictError(f"Room {room.room_number} already has an open turnover ticket ({existing[0].ticket_number}).",
                            code="DUPLICATE_ACTIVE_TICKET", details={"ticket_id": existing[0].id})
    if existing and not (data.duplicate_reason or "").strip():
        raise ValidationFailedError("A reason is required to open an additional ticket for this room.",
                                    code="EXCEPTION_REASON_REQUIRED")
    assignee = None
    if data.assigned_housekeeper_id:
        assignee = get_active_user(db, data.assigned_housekeeper_id, Department.HOUSEKEEPING, "housekeeper")

    is_exception = bool(existing)
    ticket = TurnoverTicket(
        room=room, room_id=room.id, status=TicketStatus.AWAITING_HOUSEKEEPING, priority=data.priority,
        notes=data.notes, created_by_id=actor.id, is_active=True,
        active_room_key=None if is_exception else room.id,
        is_exception=is_exception, exception_reason=data.duplicate_reason if is_exception else None,
    )
    db.add(ticket)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError(f"Room {room.room_number} already has an open turnover ticket.", code="DUPLICATE_ACTIVE_TICKET")
    ticket.ticket_number = f"TT-{utcnow():%Y%m%d}-{ticket.id:05d}"

    previous_room_status = room.operational_status
    attached = attach_direct_repairs(db, room, ticket)
    room.occupancy_status = OccupancyStatus.VACANT
    room.active_ticket_id = ticket.id
    room.active_ticket = ticket
    room.assigned_engineer_id = None
    room.operational_status = OperationalStatus.AWAITING_HOUSEKEEPING
    room.assigned_housekeeper_id = None
    audit_service.log(db, actor=actor, action="TICKET_CREATED", entity_type="ticket", entity_id=ticket.id,
                      ticket_id=ticket.id, room_id=room.id, from_status=previous_room_status,
                      to_status=TicketStatus.AWAITING_HOUSEKEEPING,
                      message=(f"{message} ({ticket.ticket_number})" if message else
                               f"Checkout recorded for room {room.room_number}; ticket {ticket.ticket_number} opened"),
                      details={"exception_reason": data.duplicate_reason} if is_exception else None)
    if attached:
        audit_service.log(db, actor=actor, action="REPAIR_ATTACHED", entity_type="ticket", entity_id=ticket.id,
                          ticket_id=ticket.id, room_id=room.id,
                          message=f"{len(attached)} open repair(s) on room {room.room_number} added to this turnover",
                          details={"repairs": [r.repair_number for r in attached]})
    if assignee:
        _assign_housekeeper(db, ticket, assignee, actor, None)
        transition(db, ticket, TicketStatus.HOUSEKEEPING_ASSIGNED, actor=actor, action="TICKET_ASSIGNED",
                   message=f"Assigned to {assignee.display_name} (Housekeeping)")
    db.commit()
    db.refresh(ticket)
    return ticket


def attach_direct_repairs(db: Session, room, ticket: TurnoverTicket) -> list[RepairRequest]:
    """Move a room's open front-desk repairs (no ticket yet) onto a new turnover ticket, so the
    room cannot be released until they are done."""
    loose = list(db.scalars(select(RepairRequest).where(
        RepairRequest.room_id == room.id, RepairRequest.ticket_id.is_(None),
        RepairRequest.status.in_(list(OPEN_REPAIR_STATUSES)))).unique().all())
    for r in loose:
        r.ticket = ticket
        r.blocks_room = False
        for sess in r.sessions:
            sess.ticket_id = ticket.id
    if loose:
        db.flush()
        db.expire(ticket, ["sessions"])
    return loose


ASSIGNABLE_HK = {TicketStatus.AWAITING_HOUSEKEEPING, TicketStatus.HOUSEKEEPING_ASSIGNED,
                 TicketStatus.HOUSEKEEPING_IN_PROGRESS, TicketStatus.RECLEAN_REQUIRED}


def assign_ticket(db: Session, actor: User, ticket_id: int, housekeeper_id: int, reason: Optional[str]) -> TurnoverTicket:
    ticket = get_ticket(db, ticket_id, lock=True)
    if ticket.status not in ASSIGNABLE_HK:
        raise WorkflowError(f"Housekeeping cannot be (re)assigned while the ticket is {ticket.status.value}.")
    assignee = get_active_user(db, housekeeper_id, Department.HOUSEKEEPING, "housekeeper")
    if ticket.assigned_housekeeper_id == assignee.id:
        return ticket
    was = ticket.assigned_housekeeper.display_name if ticket.assigned_housekeeper else None
    _assign_housekeeper(db, ticket, assignee, actor, reason)
    new_status = TicketStatus.HOUSEKEEPING_ASSIGNED if ticket.status == TicketStatus.AWAITING_HOUSEKEEPING else ticket.status
    transition(db, ticket, new_status, actor=actor, action="TICKET_REASSIGNED" if was else "TICKET_ASSIGNED",
               message=(f"Reassigned from {was} to {assignee.display_name}" if was
                        else f"Assigned to {assignee.display_name} (Housekeeping)"),
               details={"reason": reason} if reason else None)
    db.commit()
    db.refresh(ticket)
    return ticket


def update_priority(db: Session, actor: User, ticket_id: int, priority) -> TurnoverTicket:
    ticket = get_ticket(db, ticket_id, lock=True)
    if ticket.status in TERMINAL_TICKET_STATUSES:
        raise WorkflowError("Closed tickets cannot be changed.")
    previous = ticket.priority
    ticket.priority = priority
    for r in ticket.repairs:
        if r.status in OPEN_REPAIR_STATUSES:
            r.priority = priority
    audit_service.log(db, actor=actor, action="TICKET_PRIORITY_CHANGED", entity_type="ticket", entity_id=ticket.id,
                      ticket_id=ticket.id, room_id=ticket.room_id, from_status=previous, to_status=priority,
                      message=f"Priority changed from {previous.value} to {priority.value}")
    db.commit()
    return ticket


def cancel_ticket(db: Session, actor: User, ticket_id: int, reason: str, room_status: OperationalStatus) -> TurnoverTicket:
    ticket = get_ticket(db, ticket_id, lock=True)
    if ticket.status in TERMINAL_TICKET_STATUSES:
        raise WorkflowError("Ticket is already closed.")
    if room_status not in (OperationalStatus.OUT_OF_SERVICE, OperationalStatus.AWAITING_HOUSEKEEPING):
        raise WorkflowError("A cancelled ticket can leave the room Out of Service or Awaiting Housekeeping only. "
                            "Rooms reach Ready for Guest through the release workflow.")
    previous = ticket.status
    for r in ticket.repairs:
        if r.status in OPEN_REPAIR_STATUSES:
            r.status = RepairStatus.CANCELLED
    for s in ticket.sessions:
        if s.status == SessionStatus.IN_PROGRESS:
            s.status = SessionStatus.SUPERSEDED
    ticket.status = TicketStatus.CANCELLED
    ticket.is_active = False
    ticket.active_room_key = None
    ticket.cancelled_at = utcnow()
    ticket.cancel_reason = reason
    room = ticket.room
    if room.active_ticket_id == ticket.id:
        room.active_ticket_id = None
        room.operational_status = room_status
        room.assigned_housekeeper_id = None
        room.assigned_engineer_id = None
    audit_service.log(db, actor=actor, action="TICKET_CANCELLED", entity_type="ticket", entity_id=ticket.id,
                      ticket_id=ticket.id, room_id=ticket.room_id, from_status=previous, to_status=TicketStatus.CANCELLED,
                      message=f"Ticket cancelled; room set to {room_status.value}", details={"reason": reason})
    db.commit()
    db.refresh(ticket)
    return ticket


# --------------------------------------------------------------------------- final release

def release_blockers(ticket: TurnoverTicket) -> list[str]:
    if ticket.status in TERMINAL_TICKET_STATUSES:
        return [f"Ticket is {ticket.status.value.lower()}."]
    blockers: list[str] = []
    hk = [s for s in ticket.sessions if s.kind == SessionKind.HOUSEKEEPING and s.status != SessionStatus.SUPERSEDED]
    submitted = [s for s in hk if s.status == SessionStatus.SUBMITTED]
    if not submitted:
        blockers.append("Housekeeping has not submitted the cleaning and inspection checklist.")
    if any(s.status == SessionStatus.IN_PROGRESS for s in hk):
        blockers.append("A housekeeping inspection is still in progress.")
    for s in submitted:
        if s.outcome == SessionOutcome.FAIL:
            fixed = [r for r in ticket.repairs if r.source_session_id == s.id and r.status == RepairStatus.COMPLETED]
            if not fixed:
                blockers.append(f"Failed items from housekeeping round {s.round_number} have not been repaired.")
    for r in ticket.repairs:
        if r.status in OPEN_REPAIR_STATUSES:
            blockers.append(f"Repair {r.repair_number} is still open ({r.status.value.replace('_', ' ').lower()}).")
        elif r.status == RepairStatus.COMPLETED:
            eng = [s for s in ticket.sessions if s.repair_id == r.id and s.status == SessionStatus.SUBMITTED]
            if not eng or eng[-1].outcome != SessionOutcome.PASS:
                blockers.append(f"Repair {r.repair_number} has no passing engineering inspection.")
            elif any(res.result == ItemResult.FAIL for res in eng[-1].results):
                blockers.append(f"Repair {r.repair_number} has unresolved engineering failures.")
    if ticket.needs_reclean:
        blockers.append("Housekeeping must re-clean and re-inspect the room after engineering work.")
    if not blockers and ticket.status != TicketStatus.AWAITING_FINAL_VERIFICATION:
        blockers.append(f"Ticket is {ticket.status.value.replace('_', ' ').lower()}.")
    return blockers


def can_release(user: User, ticket: TurnoverTicket) -> bool:
    if user.department.value not in settings.RELEASE_DEPARTMENTS:
        return False
    if user.department == Department.FRONT_DESK:
        return True
    if user.department == Department.HOUSEKEEPING:
        return ticket.assigned_housekeeper_id == user.id
    if user.department == Department.ENGINEERING:
        return any(r.assigned_engineer_id == user.id for r in ticket.repairs)
    return False


def readiness(user: User, ticket: TurnoverTicket) -> dict:
    blockers = release_blockers(ticket)
    return {"ready": not blockers, "blockers": blockers, "can_release": not blockers and can_release(user, ticket)}


def release_ticket(db: Session, actor: User, ticket_id: int, notes: Optional[str] = None) -> TurnoverTicket:
    ticket = get_ticket(db, ticket_id, lock=True)
    if not can_release(actor, ticket):
        raise ForbiddenError("You are not authorised to release this room.", code="RELEASE_NOT_PERMITTED")
    blockers = release_blockers(ticket)
    if blockers:
        raise WorkflowError("The room cannot be marked Ready for Guest yet.", code="RELEASE_BLOCKED", details=blockers)
    previous = ticket.status
    now = utcnow()
    ticket.status = TicketStatus.CLOSED
    ticket.is_active = False
    ticket.active_room_key = None
    ticket.released_at = now
    ticket.released_by_id = actor.id
    room = ticket.room
    if room.active_ticket_id == ticket.id:
        others = [t for t in turnover_repository.active_tickets_for_room(db, room.id) if t.id != ticket.id]
        if others:
            room.active_ticket_id = others[-1].id
            sync_room(others[-1])
        else:
            room.active_ticket_id = None
            room.operational_status = OperationalStatus.READY_FOR_GUEST
            room.assigned_housekeeper_id = None
            room.assigned_engineer_id = None
            room.last_ready_at = now
    audit_service.log(db, actor=actor, action="ROOM_RELEASED", entity_type="ticket", entity_id=ticket.id,
                      ticket_id=ticket.id, room_id=room.id, from_status=previous, to_status=TicketStatus.CLOSED,
                      message=f"Room {room.room_number} released as Ready for Guest by {actor.display_name}",
                      details={"notes": notes} if notes else None)
    db.commit()
    db.refresh(ticket)
    return ticket


# --------------------------------------------------------------------------- read models

def assignments(db: Session, ticket_id: int) -> list[TicketAssignment]:
    return list(db.scalars(select(TicketAssignment).where(TicketAssignment.ticket_id == ticket_id)
                           .order_by(TicketAssignment.id)).unique().all())


def timeline(db: Session, ticket_id: int) -> list[ActivityLog]:
    return list(db.scalars(select(ActivityLog).where(ActivityLog.ticket_id == ticket_id)
                           .order_by(ActivityLog.created_at, ActivityLog.id)).unique().all())


def create_repair(db: Session, ticket: TurnoverTicket, session: InspectionSession, actor: User, notes: Optional[str]) -> RepairRequest:
    failed = [r for r in session.results if r.result == ItemResult.FAIL]
    defect = "; ".join(f"{r.item_name}: {r.remarks}" for r in failed)
    if notes:
        defect = f"{defect}\nHousekeeping note: {notes}"
    repair = RepairRequest(
        ticket=ticket, room_id=ticket.room_id, source_session_id=session.id, status=RepairStatus.NEW,
        priority=ticket.priority, reported_defect=defect[:5000], created_by_id=actor.id,
    )
    db.add(repair)
    db.flush()
    repair.repair_number = f"RR-{utcnow():%Y%m%d}-{repair.id:05d}"
    audit_service.log(db, actor=actor, action="REPAIR_CREATED", entity_type="repair", entity_id=repair.id,
                      ticket_id=ticket.id, repair_id=repair.id, room_id=ticket.room_id, to_status=RepairStatus.NEW,
                      message=f"Repair request {repair.repair_number} raised for {len(failed)} failed item(s)",
                      details={"failed_items": [r.item_name for r in failed]})
    return repair
