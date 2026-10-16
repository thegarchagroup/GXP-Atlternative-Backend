from typing import Optional

from pydantic import BaseModel, Field

from models.enums import ChecklistType, Department
from schemas.common import ORMModel, UTCDateTime


class ChecklistItemOut(ORMModel):
    id: int
    template_id: int
    name: str
    description: Optional[str] = None
    category: str
    room_type_ids: list[int]
    is_mandatory: bool
    allow_not_applicable: bool
    is_active: bool
    display_order: int
    reference_instructions: Optional[str] = None
    reference_image_url: Optional[str] = None


class ChecklistOut(ORMModel):
    id: int
    name: str
    description: Optional[str] = None
    checklist_type: ChecklistType
    department: Department
    is_active: bool
    created_at: UTCDateTime
    updated_at: UTCDateTime
    items: list[ChecklistItemOut] = []


class ChecklistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = None
    checklist_type: ChecklistType
    is_active: bool = True


class ChecklistUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ChecklistItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: Optional[str] = None
    category: str = Field(default="General", min_length=1, max_length=80)
    room_type_ids: list[int] = []
    is_mandatory: bool = True
    allow_not_applicable: bool = False
    is_active: bool = True
    display_order: int = 0
    reference_instructions: Optional[str] = None
    reference_image_url: Optional[str] = Field(default=None, max_length=500)


class ChecklistItemUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = None
    category: Optional[str] = Field(default=None, min_length=1, max_length=80)
    room_type_ids: Optional[list[int]] = None
    is_mandatory: Optional[bool] = None
    allow_not_applicable: Optional[bool] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None
    reference_instructions: Optional[str] = None
    reference_image_url: Optional[str] = Field(default=None, max_length=500)
