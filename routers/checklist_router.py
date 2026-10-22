from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.permissions import require_any, require_hk_supervisor
from database.connection import get_db
from models.enums import ChecklistType
from models.user import User
from repositories import checklist_repository
from schemas.checklist_schema import (
    ChecklistCreate, ChecklistItemCreate, ChecklistItemOut, ChecklistItemUpdate, ChecklistOut, ChecklistUpdate,
)
from schemas.common import MessageOut
from services import checklist_service

router = APIRouter(prefix="/api/v1/checklists", tags=["Checklist configuration (HK supervisor)"])


@router.get("", response_model=list[ChecklistOut])
def list_checklists(checklist_type: Optional[ChecklistType] = None, include_inactive: bool = True,
                    _: User = Depends(require_any), db: Session = Depends(get_db)):
    return [ChecklistOut.model_validate(t) for t in checklist_repository.list_templates(db, checklist_type, include_inactive)]


@router.get("/preview", response_model=list[ChecklistItemOut])
def preview(room_type_id: int, checklist_type: list[ChecklistType] | None = None,
            _: User = Depends(require_any), db: Session = Depends(get_db)):
    """Items a new inspection would contain for a room type."""
    types = checklist_type or list(ChecklistType)
    return [ChecklistItemOut.model_validate(i) for i in checklist_service.preview_for_room_type(db, types, room_type_id)]


@router.post("", response_model=ChecklistOut, status_code=201)
def create_checklist(body: ChecklistCreate, actor: User = Depends(require_hk_supervisor), db: Session = Depends(get_db)):
    return ChecklistOut.model_validate(checklist_service.create_template(db, actor, body))


@router.get("/{checklist_id}", response_model=ChecklistOut)
def get_checklist(checklist_id: int, _: User = Depends(require_any), db: Session = Depends(get_db)):
    return ChecklistOut.model_validate(checklist_service.get_template(db, checklist_id))


@router.put("/{checklist_id}", response_model=ChecklistOut)
def update_checklist(checklist_id: int, body: ChecklistUpdate, actor: User = Depends(require_hk_supervisor),
                     db: Session = Depends(get_db)):
    return ChecklistOut.model_validate(checklist_service.update_template(db, actor, checklist_id, body))


@router.delete("/{checklist_id}", response_model=MessageOut)
def delete_checklist(checklist_id: int, actor: User = Depends(require_hk_supervisor), db: Session = Depends(get_db)):
    checklist_service.delete_template(db, actor, checklist_id)
    return MessageOut(message="Checklist deleted. Existing inspections keep their recorded items.")


@router.post("/{checklist_id}/items", response_model=ChecklistItemOut, status_code=201)
def add_item(checklist_id: int, body: ChecklistItemCreate, actor: User = Depends(require_hk_supervisor),
             db: Session = Depends(get_db)):
    return ChecklistItemOut.model_validate(checklist_service.add_item(db, actor, checklist_id, body))


@router.put("/items/{item_id}", response_model=ChecklistItemOut)
def update_item(item_id: int, body: ChecklistItemUpdate, actor: User = Depends(require_hk_supervisor),
                db: Session = Depends(get_db)):
    return ChecklistItemOut.model_validate(checklist_service.update_item(db, actor, item_id, body))


@router.delete("/items/{item_id}", response_model=MessageOut)
def delete_item(item_id: int, actor: User = Depends(require_hk_supervisor), db: Session = Depends(get_db)):
    checklist_service.delete_item(db, actor, item_id)
    return MessageOut(message="Checklist item removed")
