from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.checklist import ChecklistTemplate, ChecklistTemplateItem
from models.enums import ChecklistType


def list_templates(db: Session, checklist_type: Optional[ChecklistType] = None, include_inactive: bool = True):
    stmt = select(ChecklistTemplate).where(ChecklistTemplate.is_deleted.is_(False))
    if checklist_type:
        stmt = stmt.where(ChecklistTemplate.checklist_type == checklist_type)
    if not include_inactive:
        stmt = stmt.where(ChecklistTemplate.is_active.is_(True))
    return list(db.scalars(stmt.order_by(ChecklistTemplate.checklist_type, ChecklistTemplate.id)).all())


def get_template(db: Session, template_id: int) -> Optional[ChecklistTemplate]:
    t = db.get(ChecklistTemplate, template_id)
    return t if t and not t.is_deleted else None


def get_item(db: Session, item_id: int) -> Optional[ChecklistTemplateItem]:
    i = db.get(ChecklistTemplateItem, item_id)
    return i if i and not i.is_deleted else None


def active_items_for(db: Session, types: list[ChecklistType], room_type_id: int) -> list[tuple[ChecklistTemplate, ChecklistTemplateItem]]:
    """Active items of active templates of the given types that apply to the room type."""
    stmt = (
        select(ChecklistTemplate, ChecklistTemplateItem)
        .join(ChecklistTemplateItem, ChecklistTemplateItem.template_id == ChecklistTemplate.id)
        .where(
            ChecklistTemplate.checklist_type.in_(types),
            ChecklistTemplate.is_active.is_(True),
            ChecklistTemplate.is_deleted.is_(False),
            ChecklistTemplateItem.is_active.is_(True),
            ChecklistTemplateItem.is_deleted.is_(False),
        )
        .order_by(ChecklistTemplate.id, ChecklistTemplateItem.display_order, ChecklistTemplateItem.id)
    )
    rows = db.execute(stmt).all()
    return [(t, i) for t, i in rows if not i.room_type_ids or room_type_id in i.room_type_ids]
