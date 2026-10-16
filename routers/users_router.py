from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.permissions import require_admin
from database.connection import get_db
from models.enums import Department
from models.user import User
from repositories import user_repository
from schemas.common import MessageOut, Page
from schemas.user_schema import PasswordReset, UserCreate, UserOut, UserStatusUpdate, UserUpdate
from services import user_service

router = APIRouter(prefix="/api/v1/users", tags=["Users (admin)"])


@router.get("", response_model=Page[UserOut])
def list_users(search: Optional[str] = None, department: Optional[Department] = None, is_active: Optional[bool] = None,
               page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
               _: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows, total = user_repository.search(db, search=search, department=department, is_active=is_active,
                                         page=page, page_size=page_size)
    return Page(items=[UserOut.model_validate(u) for u in rows], total=total, page=page, page_size=page_size)


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    return UserOut.model_validate(user_service.create_user(db, actor, body))


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return UserOut.model_validate(user_service.get_user(db, user_id))


@router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    return UserOut.model_validate(user_service.update_user(db, actor, user_id, body))


@router.patch("/{user_id}/status", response_model=UserOut)
def set_status(user_id: int, body: UserStatusUpdate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    return UserOut.model_validate(user_service.set_status(db, actor, user_id, body.is_active))


@router.post("/{user_id}/reset-password", response_model=UserOut)
def reset_password(user_id: int, body: PasswordReset, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    return UserOut.model_validate(user_service.reset_password(db, actor, user_id, body.new_password))


@router.delete("/{user_id}", response_model=MessageOut)
def delete_user(user_id: int, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    mode = user_service.delete_user(db, actor, user_id)
    return MessageOut(message="User deleted" if mode == "hard" else
                      "User has history, so the account was deactivated and archived instead of erased")
