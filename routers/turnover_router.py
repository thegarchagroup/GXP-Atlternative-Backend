from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.dependencies import get_current_user
from core.permissions import require_admin, require_any
from database.connection import get_db
from models.enums import Priority, TicketStatus
from models.user import User
from repositories import turnover_repository
from schemas.common import Page, user_brief
from schemas.inspection_schema import session_out
from schemas.repair_schema import repair_out
from schemas.turnover_schema import (
    AssignmentOut, ReadinessOut, SubmitRequest, TicketAssignRequest, TicketCancelRequest, TicketCreate,
    TicketDetailOut, TicketOut, TicketPriorityUpdate, TimelineEntry, ticket_out, timeline_entry,
)
from services import housekeeping_service, turnover_service

router = APIRouter(prefix="/api/v1/turnover", tags=["Turnover tickets"])


def build_detail(db: Session, user: User, ticket) -> TicketDetailOut:
    base = ticket_out(ticket).model_dump()
    return TicketDetailOut(
        **base,
        sessions=[session_out(s) for s in ticket.sessions],
        repairs=[repair_out(r) for r in ticket.repairs],
        assignments=[AssignmentOut(id=a.id, department=a.department.value, repair_id=a.repair_id,
                                   assignee=user_brief(a.assignee), previous_assignee=user_brief(a.previous_assignee),
                                   assigned_by=user_brief(a.assigned_by), reason=a.reason, assigned_at=a.assigned_at)
                     for a in turnover_service.assignments(db, ticket.id)],
        readiness=ReadinessOut(**turnover_service.readiness(user, ticket)),
    )


@router.get("", response_model=Page[TicketOut])
def list_tickets(
    search: Optional[str] = None,
    status: Optional[list[TicketStatus]] = Query(None),
    priority: Optional[Priority] = None,
    housekeeper_id: Optional[int] = None,
    room_id: Optional[int] = None,
    active_only: bool = False,
    created_from: Optional[date] = None,
    created_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows, total = turnover_repository.search_tickets(
        db, search=search, status=status, priority=priority, housekeeper_id=housekeeper_id, room_id=room_id,
        active_only=active_only, created_from=created_from, created_to=created_to, page=page, page_size=page_size)
    return Page(items=[ticket_out(t) for t in rows], total=total, page=page, page_size=page_size)


@router.post("", response_model=TicketDetailOut, status_code=201)
def create_ticket(body: TicketCreate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Record checkout and open a turnover ticket. Optionally assign a housekeeper immediately."""
    return build_detail(db, actor, turnover_service.create_ticket(db, actor, body))


@router.get("/{ticket_id}", response_model=TicketDetailOut)
def get_ticket(ticket_id: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    ticket = turnover_service.get_ticket(db, ticket_id)
    turnover_service.ensure_can_view(user, ticket)
    return build_detail(db, user, ticket)


@router.post("/{ticket_id}/assign", response_model=TicketDetailOut)
def assign(ticket_id: int, body: TicketAssignRequest, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    return build_detail(db, actor, turnover_service.assign_ticket(db, actor, ticket_id, body.housekeeper_id, body.reason))


@router.post("/{ticket_id}/start", response_model=TicketDetailOut)
def start(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Start housekeeping work (assigned housekeeper only). Same as POST /housekeeping/{id}/start."""
    return build_detail(db, user, housekeeping_service.start(db, user, ticket_id))


@router.get("/{ticket_id}/timeline", response_model=list[TimelineEntry])
def timeline(ticket_id: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    ticket = turnover_service.get_ticket(db, ticket_id)
    turnover_service.ensure_can_view(user, ticket)
    return [timeline_entry(log) for log in turnover_service.timeline(db, ticket_id)]


@router.get("/{ticket_id}/readiness", response_model=ReadinessOut)
def readiness(ticket_id: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    ticket = turnover_service.get_ticket(db, ticket_id)
    turnover_service.ensure_can_view(user, ticket)
    return ReadinessOut(**turnover_service.readiness(user, ticket))


@router.post("/{ticket_id}/release", response_model=TicketDetailOut)
def release(ticket_id: int, body: Optional[SubmitRequest] = None, user: User = Depends(require_any),
            db: Session = Depends(get_db)):
    """Final release to Ready for Guest. Fails with RELEASE_BLOCKED and a list of blockers
    unless every housekeeping and engineering condition is met."""
    return build_detail(db, user, turnover_service.release_ticket(db, user, ticket_id, body.notes if body else None))


@router.post("/{ticket_id}/cancel", response_model=TicketDetailOut)
def cancel(ticket_id: int, body: TicketCancelRequest, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    return build_detail(db, actor, turnover_service.cancel_ticket(db, actor, ticket_id, body.reason, body.room_status))


@router.patch("/{ticket_id}/priority", response_model=TicketDetailOut)
def set_priority(ticket_id: int, body: TicketPriorityUpdate, actor: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    return build_detail(db, actor, turnover_service.update_priority(db, actor, ticket_id, body.priority))
