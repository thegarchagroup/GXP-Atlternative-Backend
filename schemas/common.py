from datetime import datetime, timezone
from typing import Annotated, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, PlainSerializer


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UTCDateTime = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str, when_used="json")]

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class UserBrief(ORMModel):
    id: int
    user_id: str
    display_name: str
    department: str
    role: str = ""


class MessageOut(BaseModel):
    message: str


def user_brief(user) -> Optional[UserBrief]:
    return UserBrief.model_validate(user) if user is not None else None
