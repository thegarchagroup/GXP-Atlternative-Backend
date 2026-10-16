from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.permissions import require_any, require_housekeeping
from database.connection import get_db
from models.user import User
from schemas.inspection_schema import ChecklistSaveRequest, InspectionSessionOut, ResultUpdate, session_out
from schemas.turnover_schema import TicketDetailOut, TicketOut, ticket_out
from services import housekeeping_service
from routers.turnover_router import build_detail

router = APIRouter(prefix="/api/v1/housekeeping", tags=["Housekeeping"])


class HousekeepingChecklistOut(BaseModel):
    ticket: TicketOut
    session: Optional[InspectionSessionOut] = None


class HousekeepingSubmit(BaseModel):
    notes: Optional[str] = None
    items: list[ResultUpdate] = []


@router.get("/my-tickets", response_model=list[TicketOut])
def my_tickets(bucket: Optional[Literal["open", "pending", "in_progress", "engineering", "completed", "all"]] = "all",
               user: User = Depends(require_housekeeping), db: Session = Depends(get_db)):
    return [ticket_out(t) for t in housekeeping_service.my_tickets(db, user, bucket)]


@router.post("/{ticket_id}/start", response_model=TicketDetailOut)
def start(ticket_id: int, user: User = Depends(require_housekeeping), db: Session = Depends(get_db)):
    return build_detail(db, user, housekeeping_service.start(db, user, ticket_id))


@router.get("/{ticket_id}/checklist", response_model=HousekeepingChecklistOut)
def get_checklist(ticket_id: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    ticket, session = housekeeping_service.checklist(db, user, ticket_id)
    return HousekeepingChecklistOut(ticket=ticket_out(ticket), session=session_out(session) if session else None)


@router.put("/{ticket_id}/checklist", response_model=HousekeepingChecklistOut)
def save_checklist(ticket_id: int, body: ChecklistSaveRequest, user: User = Depends(require_housekeeping),
                   db: Session = Depends(get_db)):
    ticket, session = housekeeping_service.save_checklist(db, user, ticket_id, body.items)
    return HousekeepingChecklistOut(ticket=ticket_out(ticket), session=session_out(session))


@router.post("/{ticket_id}/submit", response_model=TicketDetailOut)
def submit(ticket_id: int, body: HousekeepingSubmit, user: User = Depends(require_housekeeping),
           db: Session = Depends(get_db)):
    """Submit cleaning and inspection. Any failed item opens an engineering repair request."""
    ticket, _ = housekeeping_service.submit(db, user, ticket_id, body.notes, body.items)
    return build_detail(db, user, ticket)
