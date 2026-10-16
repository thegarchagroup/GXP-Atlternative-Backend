from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Naive UTC timestamp. All timestamps are stored in UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


def enum_type(enum_cls):
    """Store enums as validated VARCHAR values (portable across MySQL and SQLite)."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=40,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )
