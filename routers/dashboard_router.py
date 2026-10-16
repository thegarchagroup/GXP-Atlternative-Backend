from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.permissions import require_admin, require_any, require_engineering, require_housekeeping
from database.connection import get_db
from models.enums import Department
from models.user import User
from schemas.common import UserBrief, user_brief
from schemas.dashboard_schema import EngineeringSummary, FrontDeskSummary, HousekeepingSummary, NotificationOut
from services import dashboard_service, notification_service

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboards"])


@router.get("/frontdesk", response_model=FrontDeskSummary)
def frontdesk(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return dashboard_service.frontdesk(db)


@router.get("/housekeeping", response_model=HousekeepingSummary)
def housekeeping(user: User = Depends(require_housekeeping), db: Session = Depends(get_db)):
    return dashboard_service.housekeeping(db, user)


@router.get("/engineering", response_model=EngineeringSummary)
def engineering(user: User = Depends(require_engineering), db: Session = Depends(get_db)):
    return dashboard_service.engineering(db, user)


@router.get("/notifications", response_model=list[NotificationOut])
def notifications(since: Optional[datetime] = None, limit: int = Query(30, ge=1, le=100), include_own: bool = False,
                  user: User = Depends(require_any), db: Session = Depends(get_db)):
    """Recent workflow activity relevant to the signed-in user (poll with `since`)."""
    return [NotificationOut(id=n.id, action=n.action, message=n.message, ticket_id=n.ticket_id, repair_id=n.repair_id,
                            room_id=n.room_id, actor=user_brief(n.actor), created_at=n.created_at)
            for n in notification_service.for_user(db, user, since, limit, include_own)]


@router.get("/staff", response_model=list[UserBrief])
def staff(department: Department, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Active staff of a department, for assignment pickers."""
    rows = db.scalars(select(User).where(User.department == department, User.is_active.is_(True),
                                         User.is_deleted.is_(False)).order_by(User.display_name)).all()
    return [UserBrief.model_validate(u) for u in rows]
