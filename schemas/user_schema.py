from typing import Optional

from pydantic import BaseModel, Field, field_validator

from models.enums import Department, Role
from schemas.common import ORMModel, UTCDateTime

USER_ID_PATTERN = r"^[A-Za-z0-9._-]{3,80}$"


class UserOut(ORMModel):
    id: int
    user_id: str
    display_name: str
    department: Department
    role: Role
    is_active: bool
    must_change_password: bool
    last_login_at: Optional[UTCDateTime] = None
    created_at: UTCDateTime
    updated_at: UTCDateTime


class UserCreate(BaseModel):
    user_id: str = Field(pattern=USER_ID_PATTERN)
    display_name: str = Field(min_length=1, max_length=120)
    role: Optional[Role] = None
    department: Optional[Department] = None  # older clients: role is derived from it
    password: str = Field(min_length=8, max_length=72)

    @field_validator("display_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Display name is required")
        return v


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    role: Optional[Role] = None
    department: Optional[Department] = None


class UserStatusUpdate(BaseModel):
    is_active: bool


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=72)
