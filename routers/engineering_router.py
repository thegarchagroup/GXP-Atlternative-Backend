from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.permissions import require_admin, require_any, require_engineering, require_engineering_or_admin
from database.connection import get_db
from models.enums import RepairStatus
from models.user import User
from schemas.common import Page
from schemas.inspection_schema import EngineeringChecklistSaveRequest, InspectionSessionOut, result_out, session_out
from schemas.repair_schema import (
    DirectRepairCreate, RepairAssignRequest, RepairCompleteRequest, RepairDetailOut, RepairOut, RepairReopenRequest, repair_out,
)
from services import engineering_service

router = APIRouter(prefix="/api/v1/engineering", tags=["Engineering"])


class EngineeringChecklistOut(BaseModel):
    repair: RepairOut
    session: Optional[InspectionSessionOut] = None


def build_repair_detail(db: Session, repair) -> RepairDetailOut:
    source = None
    if repair.ticket is not None and repair.source_session_id:
        source = next((s for s in repair.ticket.sessions if s.id == repair.source_session_id), None)
    failed = [r for r in source.results if r.result.value == "FAIL"] if source else []
    sessions = list(repair.sessions)
    return RepairDetailOut(
        **repair_out(repair).model_dump(),
        failed_items=[result_out(r) for r in failed],
        housekeeping_notes=source.notes if source else None,
        sessions=[session_out(s) for s in sessions],
        room_repair_history=[repair_out(r) for r in engineering_service.room_history(db, repair)],
    )


@router.get("/my-tickets", response_model=Page[RepairOut])
def my_tickets(scope: Optional[Literal["all", "new", "assigned", "in_progress", "awaiting_verification", "completed",
                                       "reopened", "open"]] = "all",
               search: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
               user: User = Depends(require_engineering), db: Session = Depends(get_db)):
    """Repairs assigned to me, plus unassigned requests the team can claim (scope=all or new)."""
    rows, total = engineering_service.list_for_engineer(db, user, scope, search, page, page_size)
    return Page(items=[repair_out(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/repairs", response_model=Page[RepairOut])
def list_repairs(status: Optional[list[RepairStatus]] = Query(None), engineer_id: Optional[int] = None,
                 search: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
                 _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """All repair requests (front desk monitoring)."""
    rows, total = engineering_service.list_all(db, status, engineer_id, search, page, page_size)
    return Page(items=[repair_out(r) for r in rows], total=total, page=page, page_size=page_size)


@router.post("/repairs", response_model=RepairDetailOut, status_code=201)
def create_direct_repair(body: DirectRepairCreate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Front desk raises a repair directly (e.g. a guest complaint or planned maintenance).
    - Room in a turnover: the repair joins that ticket; the room can't be released until it's done.
    - Vacant, ready room: blocked from sale until engineering completes, then ready again.
    - Occupied room: stays occupied; the repair is tracked against it."""
    repair = engineering_service.create_direct(db, actor, room_id=body.room_id, reported_defect=body.reported_defect,
                                               priority=body.priority, engineer_id=body.engineer_id)
    return build_repair_detail(db, repair)


@router.get("/{repair_id}", response_model=RepairDetailOut)
def get_repair(repair_id: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    repair = engineering_service.get_repair(db, repair_id)
    engineering_service.ensure_can_view(user, repair)
    return build_repair_detail(db, repair)


@router.post("/{repair_id}/assign", response_model=RepairDetailOut)
def assign(repair_id: int, body: RepairAssignRequest, user: User = Depends(require_engineering_or_admin),
           db: Session = Depends(get_db)):
    """Front desk assigns any engineer; an engineer may claim an unassigned repair for themselves."""
    return build_repair_detail(db, engineering_service.assign(db, user, repair_id, body.engineer_id, body.reason))


@router.post("/{repair_id}/start", response_model=RepairDetailOut)
def start(repair_id: int, user: User = Depends(require_engineering), db: Session = Depends(get_db)):
    return build_repair_detail(db, engineering_service.start(db, user, repair_id))


@router.get("/{repair_id}/checklist", response_model=EngineeringChecklistOut)
def get_checklist(repair_id: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    repair = engineering_service.get_repair(db, repair_id)
    engineering_service.ensure_can_view(user, repair)
    session = engineering_service.current_session(repair)
    return EngineeringChecklistOut(repair=repair_out(repair), session=session_out(session) if session else None)


@router.put("/{repair_id}/checklist", response_model=EngineeringChecklistOut)
def save_checklist(repair_id: int, body: EngineeringChecklistSaveRequest, user: User = Depends(require_engineering),
                   db: Session = Depends(get_db)):
    repair = engineering_service.save_checklist(db, user, repair_id, body.items, body.diagnosis, body.repair_notes)
    session = engineering_service.current_session(repair)
    return EngineeringChecklistOut(repair=repair_out(repair), session=session_out(session) if session else None)



@router.post("/{repair_id}/complete", response_model=RepairDetailOut)
def complete(repair_id: int, body: RepairCompleteRequest, user: User = Depends(require_engineering),
             db: Session = Depends(get_db)):
    """Complete the repair. Rejected while any engineering check fails or a required check is pending.
    Set requires_recleaning=true to send the room back to Housekeeping."""
    repair = engineering_service.complete(db, user, repair_id, requires_recleaning=body.requires_recleaning,
                                          diagnosis=body.diagnosis, repair_notes=body.repair_notes)
    return build_repair_detail(db, repair)


@router.post("/{repair_id}/reopen", response_model=RepairDetailOut)
def reopen(repair_id: int, body: RepairReopenRequest, user: User = Depends(require_engineering_or_admin),
           db: Session = Depends(get_db)):
    return build_repair_detail(db, engineering_service.reopen(db, user, repair_id, body.reason))
