from sqlalchemy.orm import Session

from core.exceptions import NotFoundError, ValidationFailedError
from models.checklist import ChecklistTemplate, ChecklistTemplateItem
from models.enums import CHECKLIST_DEPARTMENT, ChecklistType
from models.room import RoomType
from repositories import checklist_repository
from schemas.checklist_schema import ChecklistCreate, ChecklistItemCreate, ChecklistItemUpdate, ChecklistUpdate
from services import audit_service


def get_template(db: Session, template_id: int) -> ChecklistTemplate:
    t = checklist_repository.get_template(db, template_id)
    if not t:
        raise NotFoundError("Checklist not found.")
    return t


def _validate_room_types(db: Session, ids: list[int]) -> list[int]:
    clean = sorted(set(int(i) for i in ids))
    for rid in clean:
        if not db.get(RoomType, rid):
            raise ValidationFailedError(f"Room type {rid} does not exist.", code="INVALID_ROOM_TYPE")
    return clean


def create_template(db: Session, actor, data: ChecklistCreate) -> ChecklistTemplate:
    t = ChecklistTemplate(
        name=data.name.strip(), description=data.description, checklist_type=data.checklist_type,
        department=CHECKLIST_DEPARTMENT[data.checklist_type], is_active=data.is_active, created_by_id=actor.id,
    )
    db.add(t)
    db.flush()
    audit_service.log(db, actor=actor, action="CHECKLIST_CREATED", entity_type="checklist", entity_id=t.id,
                      message=f"Created checklist '{t.name}' ({t.checklist_type.value})")
    db.commit()
    db.refresh(t)
    return t


def update_template(db: Session, actor, template_id: int, data: ChecklistUpdate) -> ChecklistTemplate:
    t = get_template(db, template_id)
    if data.name is not None:
        t.name = data.name.strip()
    if data.description is not None:
        t.description = data.description
    if data.is_active is not None:
        t.is_active = data.is_active
    audit_service.log(db, actor=actor, action="CHECKLIST_UPDATED", entity_type="checklist", entity_id=t.id,
                      message=f"Updated checklist '{t.name}'", details=data.model_dump(exclude_none=True))
    db.commit()
    db.refresh(t)
    return t


def delete_template(db: Session, actor, template_id: int) -> None:
    """Soft delete: in-progress and historical inspections keep their own snapshots."""
    t = get_template(db, template_id)
    t.is_deleted = True
    t.is_active = False
    audit_service.log(db, actor=actor, action="CHECKLIST_DELETED", entity_type="checklist", entity_id=t.id,
                      message=f"Deleted checklist '{t.name}'")
    db.commit()


def add_item(db: Session, actor, template_id: int, data: ChecklistItemCreate) -> ChecklistTemplateItem:
    t = get_template(db, template_id)
    item = ChecklistTemplateItem(template_id=t.id, **data.model_dump(exclude={"room_type_ids"}),
                                 room_type_ids=_validate_room_types(db, data.room_type_ids))
    item.name = item.name.strip()
    db.add(item)
    db.flush()
    audit_service.log(db, actor=actor, action="CHECKLIST_ITEM_CREATED", entity_type="checklist_item", entity_id=item.id,
                      message=f"Added '{item.name}' to checklist '{t.name}'")
    db.commit()
    return item


def update_item(db: Session, actor, item_id: int, data: ChecklistItemUpdate) -> ChecklistTemplateItem:
    item = checklist_repository.get_item(db, item_id)
    if not item:
        raise NotFoundError("Checklist item not found.")
    values = data.model_dump(exclude_unset=True)
    if "room_type_ids" in values and values["room_type_ids"] is not None:
        values["room_type_ids"] = _validate_room_types(db, values["room_type_ids"])
    for key, value in values.items():
        if value is None and key in {"name", "category", "is_mandatory", "allow_not_applicable", "is_active",
                                      "display_order", "room_type_ids"}:
            continue
        setattr(item, key, value)
    audit_service.log(db, actor=actor, action="CHECKLIST_ITEM_UPDATED", entity_type="checklist_item", entity_id=item.id,
                      message=f"Updated checklist item '{item.name}'", details={k: str(v) for k, v in values.items()})
    db.commit()
    return item


def delete_item(db: Session, actor, item_id: int) -> None:
    item = checklist_repository.get_item(db, item_id)
    if not item:
        raise NotFoundError("Checklist item not found.")
    item.is_deleted = True
    item.is_active = False
    audit_service.log(db, actor=actor, action="CHECKLIST_ITEM_DELETED", entity_type="checklist_item", entity_id=item.id,
                      message=f"Removed checklist item '{item.name}'")
    db.commit()


def preview_for_room_type(db: Session, types: list[ChecklistType], room_type_id: int):
    return [item for _, item in checklist_repository.active_items_for(db, types, room_type_id)]
