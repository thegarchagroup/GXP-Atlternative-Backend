"""Activity feed used by the header notification bell (polled by the web app)."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from models.audit import ActivityLog
from models.enums import Department, Role
from models.repair import RepairRequest
from models.turnover import TurnoverTicket
from models.user import User

HIDDEN_ACTIONS = {"AUTH_LOGIN", "AUTH_LOGOUT", "AUTH_PASSWORD_CHANGED"}


def for_user(db: Session, user: User, since: Optional[datetime], limit: int = 30, include_own: bool = False) -> list[ActivityLog]:
    stmt = select(ActivityLog).where(ActivityLog.action.not_in(HIDDEN_ACTIONS),
                                    or_(ActivityLog.ticket_id.is_not(None), ActivityLog.repair_id.is_not(None)))
    if user.role == Role.HK_SUPERVISOR:
        stmt = select(ActivityLog).where(ActivityLog.action.not_in(HIDDEN_ACTIONS),
                                         ActivityLog.entity_type.in_(["daily_room", "daily_sheet"]))
    elif user.department == Department.HOUSEKEEPING:
        from models.daily_sheet import DailySheetRoom
        mine = select(DailySheetRoom.id).where(DailySheetRoom.assigned_ra_id == user.id)
        my_tickets = select(TurnoverTicket.id).where(TurnoverTicket.assigned_housekeeper_id == user.id)
        stmt = select(ActivityLog).where(ActivityLog.action.not_in(HIDDEN_ACTIONS), or_(
            ActivityLog.ticket_id.in_(my_tickets),
            and_(ActivityLog.entity_type == "daily_room", ActivityLog.entity_id.in_(mine))))
    elif user.department == Department.ENGINEERING:
        my_repairs = select(RepairRequest.id).where(or_(RepairRequest.assigned_engineer_id == user.id,
                                                        RepairRequest.assigned_engineer_id.is_(None)))
        stmt = stmt.where(ActivityLog.repair_id.in_(my_repairs))
    if since is not None:
        stmt = stmt.where(ActivityLog.created_at > _to_naive_utc(since))
    if not include_own:
        stmt = stmt.where(ActivityLog.actor_id != user.id)
    return list(db.scalars(stmt.order_by(ActivityLog.id.desc()).limit(limit)).unique().all())


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
