from typing import Optional

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin, enum_type
from models.enums import ChecklistType, Department


class ChecklistTemplate(Base, TimestampMixin):
    __tablename__ = "checklist_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checklist_type: Mapped[ChecklistType] = mapped_column(enum_type(ChecklistType), nullable=False, index=True)
    department: Mapped[Department] = mapped_column(enum_type(Department), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    items = relationship(
        "ChecklistTemplateItem",
        back_populates="template",
        primaryjoin="and_(ChecklistTemplate.id == ChecklistTemplateItem.template_id, ChecklistTemplateItem.is_deleted == False)",
        order_by="(ChecklistTemplateItem.display_order, ChecklistTemplateItem.id)",
        lazy="selectin",
        viewonly=True,
    )


class ChecklistTemplateItem(Base, TimestampMixin):
    __tablename__ = "checklist_template_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("checklist_templates.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="General")
    # Empty list = applies to every room type.
    room_type_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_not_applicable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reference_instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference_image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    template = relationship("ChecklistTemplate", back_populates="items", viewonly=True)
