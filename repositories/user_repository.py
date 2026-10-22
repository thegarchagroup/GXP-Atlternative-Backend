from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from models.enums import Department, Role
from models.user import User


def get_by_id(db: Session, pk: int) -> Optional[User]:
    return db.get(User, pk)


def get_by_login(db: Session, user_id: str) -> Optional[User]:
    return db.scalar(select(User).where(func.lower(User.user_id) == user_id.strip().lower()))


def count_active_admins(db: Session, exclude_id: Optional[int] = None) -> int:
    stmt = select(func.count(User.id)).where(
        User.role == Role.ADMIN, User.is_active.is_(True), User.is_deleted.is_(False)
    )
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return db.scalar(stmt) or 0


def search(db: Session, *, search: Optional[str], department: Optional[Department], is_active: Optional[bool],
           page: int, page_size: int, roles: Optional[set] = None) -> tuple[list[User], int]:
    stmt = select(User).where(User.is_deleted.is_(False))
    if roles is not None:
        stmt = stmt.where(User.role.in_(list(roles)))
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(User.user_id.ilike(like), User.display_name.ilike(like)))
    if department:
        stmt = stmt.where(User.department == department)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(User.department, User.role, User.display_name).offset((page - 1) * page_size).limit(page_size)).all()
    return list(rows), total
