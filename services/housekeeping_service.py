from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.exceptions import ForbiddenError, ValidationFailedError, WorkflowError
from database.base import utcnow
from models.enums import Department, ItemResult, SessionKind, SessionOutcome, SessionStatus, TicketStatus
from models.turnover import TurnoverTicket
from models.user import User
from schemas.inspection_schema import ResultUpdate
from services import turnover_service as wf

PENDING = {TicketStatus.HOUSEKEEPING_ASSIGNED, TicketStatus.RECLEAN_REQUIRED}
WITH_ENGINEERING = {TicketStatus.ENGINEERING_REQUIRED, TicketStatus.ENGINEERING_ASSIGNED, TicketStatus.ENGINEERING_IN_PROGRESS}
DONE = {TicketStatus.AWAITING_FINAL_VERIFICATION, TicketStatus.CLOSED}

BUCKETS = {
    "pending": PENDING,
    "in_progress": {TicketStatus.HOUSEKEEPING_IN_PROGRESS},
    "engineering": WITH_ENGINEERING,
    "completed": DONE,
}


def my_tickets(db: Session, user: User, bucket: Optional[str] = None, limit: int = 200) -> list[TurnoverTicket]:
    stmt = select(TurnoverTicket).where(TurnoverTicket.assigned_housekeeper_id == user.id,
                                        TurnoverTicket.status != TicketStatus.CANCELLED)
    if bucket in BUCKETS:
        stmt = stmt.where(TurnoverTicket.status.in_(list(BUCKETS[bucket])))
    elif bucket == "open":
        stmt = stmt.where(TurnoverTicket.is_active.is_(True))
    rows = db.scalars(stmt.order_by(TurnoverTicket.is_active.desc(), TurnoverTicket.created_at.desc()).limit(limit)).unique().all()
    return list(rows)


def _ensure_assignee(user: User, ticket: TurnoverTicket) -> None:
    if user.department != Department.HOUSEKEEPING or ticket.assigned_housekeeper_id != user.id:
        raise ForbiddenError("This ticket is assigned to another housekeeper.", code="NOT_ASSIGNEE")


def start(db: Session, user: User, ticket_id: int) -> TurnoverTicket:
    ticket = wf.get_ticket(db, ticket_id, lock=True)
    _ensure_assignee(user, ticket)
    if ticket.status not in PENDING:
        raise WorkflowError(f"Housekeeping can only start a ticket that is assigned or returned for re-cleaning "
                            f"(current status: {ticket.status.value}).")
    is_reclean = ticket.status == TicketStatus.RECLEAN_REQUIRED
    wf.start_session(db, ticket, kind=SessionKind.HOUSEKEEPING, inspector=user, is_reclean=is_reclean)
    if ticket.housekeeping_started_at is None:
        ticket.housekeeping_started_at = utcnow()
    wf.transition(db, ticket, TicketStatus.HOUSEKEEPING_IN_PROGRESS, actor=user, action="HOUSEKEEPING_STARTED",
                  message=f"{user.display_name} started {'re-cleaning' if is_reclean else 'housekeeping'}")
    db.commit()
    db.refresh(ticket)
    return ticket


def checklist(db: Session, user: User, ticket_id: int):
    ticket = wf.get_ticket(db, ticket_id)
    wf.ensure_can_view(user, ticket)
    return ticket, wf.current_session(ticket, kind=SessionKind.HOUSEKEEPING)


def _open_session(user: User, ticket: TurnoverTicket):
    _ensure_assignee(user, ticket)
    if ticket.status != TicketStatus.HOUSEKEEPING_IN_PROGRESS:
        raise WorkflowError("Start the ticket before recording checklist results.", code="NOT_STARTED")
    session = wf.current_session(ticket, kind=SessionKind.HOUSEKEEPING)
    if not session or session.status != SessionStatus.IN_PROGRESS:
        raise WorkflowError("There is no open housekeeping inspection on this ticket.", code="SESSION_CLOSED")
    return session


def save_checklist(db: Session, user: User, ticket_id: int, items: list[ResultUpdate]):
    ticket = wf.get_ticket(db, ticket_id, lock=True)
    session = _open_session(user, ticket)
    wf.save_results(db, session, user, items)
    db.commit()
    db.refresh(session)
    return ticket, session


def submit(db: Session, user: User, ticket_id: int, notes: Optional[str], items: Optional[list[ResultUpdate]] = None):
    ticket = wf.get_ticket(db, ticket_id, lock=True)
    session = _open_session(user, ticket)
    if items:
        wf.save_results(db, session, user, items)
    problems = wf.validate_for_submit(session)
    if problems:
        raise ValidationFailedError("The checklist is incomplete.", code="CHECKLIST_INCOMPLETE", details=problems)

    now = utcnow()
    failed = [r for r in session.results if r.result == ItemResult.FAIL]
    session.status = SessionStatus.SUBMITTED
    session.submitted_at = now
    session.submitted_by_id = user.id
    session.notes = notes
    session.outcome = SessionOutcome.FAIL if failed else SessionOutcome.PASS
    ticket.room.last_inspection_at = now
    ticket.needs_reclean = False

    if failed:
        repair = wf.create_repair(db, ticket, session, user, notes)
        wf.transition(db, ticket, wf.derive_post_housekeeping_status(ticket), actor=user, action="HOUSEKEEPING_FAILED",
                      repair=repair,
                      message=f"Inspection submitted with {len(failed)} failed item(s); sent to Engineering",
                      details={"failed_items": [r.item_name for r in failed]})
    else:
        ticket.housekeeping_completed_at = now
        wf.transition(db, ticket, wf.derive_post_housekeeping_status(ticket), actor=user, action="HOUSEKEEPING_PASSED",
                      message="Cleaning and inspection completed; all items passed")
    db.commit()
    db.refresh(ticket)
    return ticket, session
