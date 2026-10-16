from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from core.security import PASSWORD_RULES, hash_password, password_is_strong
from models.audit import ActivityLog
from models.enums import Department
from models.inspection import Attachment, InspectionResult, InspectionSession
from models.repair import RepairRequest
from models.turnover import TicketAssignment, TurnoverTicket
from models.user import User
from repositories import user_repository
from schemas.user_schema import UserCreate, UserUpdate
from services import audit_service


def get_user(db: Session, pk: int) -> User:
    user = user_repository.get_by_id(db, pk)
    if not user or user.is_deleted:
        raise NotFoundError("User not found.")
    return user


def _ensure_not_last_admin(db: Session, user: User, action: str) -> None:
    if user.department == Department.FRONT_DESK and user.is_active:
        if user_repository.count_active_admins(db, exclude_id=user.id) == 0:
            raise ConflictError(f"Cannot {action} the last active Front Desk administrator.", code="LAST_ADMIN")


def create_user(db: Session, actor: User, data: UserCreate) -> User:
    if not password_is_strong(data.password):
        raise ValidationFailedError(f"Password must be {PASSWORD_RULES}.", code="WEAK_PASSWORD")
    if user_repository.get_by_login(db, data.user_id):
        raise ConflictError("That user ID is already taken.", code="USER_ID_TAKEN")
    user = User(
        user_id=data.user_id.strip(),
        display_name=data.display_name,
        department=data.department,
        password_hash=hash_password(data.password),
        must_change_password=True,
        created_by_id=actor.id,
    )
    db.add(user)
    db.flush()
    audit_service.log(db, actor=actor, action="USER_CREATED", entity_type="user", entity_id=user.id,
                      message=f"Created user {user.user_id} ({user.department.value})")
    db.commit()
    return user


def update_user(db: Session, actor: User, pk: int, data: UserUpdate) -> User:
    user = get_user(db, pk)
    changes = {}
    if data.display_name is not None and data.display_name.strip() != user.display_name:
        changes["display_name"] = [user.display_name, data.display_name.strip()]
        user.display_name = data.display_name.strip()
    if data.department is not None and data.department != user.department:
        _ensure_not_last_admin(db, user, "move")
        changes["department"] = [user.department.value, data.department.value]
        user.department = data.department
        user.token_version += 1  # existing sessions carry the old department
    if changes:
        audit_service.log(db, actor=actor, action="USER_UPDATED", entity_type="user", entity_id=user.id,
                          message=f"Updated user {user.user_id}", details=changes)
        db.commit()
    return user


def set_status(db: Session, actor: User, pk: int, is_active: bool) -> User:
    user = get_user(db, pk)
    if user.is_active == is_active:
        return user
    if not is_active:
        _ensure_not_last_admin(db, user, "deactivate")
        user.token_version += 1
    user.is_active = is_active
    audit_service.log(db, actor=actor, action="USER_ACTIVATED" if is_active else "USER_DEACTIVATED",
                      entity_type="user", entity_id=user.id,
                      message=f"{'Activated' if is_active else 'Deactivated'} user {user.user_id}")
    db.commit()
    return user


def reset_password(db: Session, actor: User, pk: int, new_password: str) -> User:
    user = get_user(db, pk)
    if not password_is_strong(new_password):
        raise ValidationFailedError(f"Password must be {PASSWORD_RULES}.", code="WEAK_PASSWORD")
    user.password_hash = hash_password(new_password)
    user.must_change_password = True
    user.token_version += 1
    audit_service.log(db, actor=actor, action="USER_PASSWORD_RESET", entity_type="user", entity_id=user.id,
                      message=f"Reset password for {user.user_id}")
    db.commit()
    return user


def _has_history(db: Session, pk: int) -> bool:
    checks = [
        select(func.count(TurnoverTicket.id)).where(or_(TurnoverTicket.created_by_id == pk,
                                                       TurnoverTicket.assigned_housekeeper_id == pk,
                                                       TurnoverTicket.released_by_id == pk)),
        select(func.count(RepairRequest.id)).where(or_(RepairRequest.assigned_engineer_id == pk,
                                                      RepairRequest.created_by_id == pk)),
        select(func.count(TicketAssignment.id)).where(or_(TicketAssignment.assignee_id == pk,
                                                         TicketAssignment.assigned_by_id == pk)),
        select(func.count(InspectionSession.id)).where(InspectionSession.inspector_id == pk),
        select(func.count(InspectionResult.id)).where(InspectionResult.inspector_id == pk),
        select(func.count(Attachment.id)).where(Attachment.uploaded_by_id == pk),
        select(func.count(ActivityLog.id)).where(ActivityLog.actor_id == pk),
        select(func.count(User.id)).where(User.created_by_id == pk),
    ]
    return any((db.scalar(q) or 0) > 0 for q in checks)


def delete_user(db: Session, actor: User, pk: int) -> str:
    """Hard-delete only users with no history; otherwise soft-delete (keeps audit trail intact)."""
    user = get_user(db, pk)
    if user.id == actor.id:
        raise ConflictError("You cannot delete your own account.", code="SELF_DELETE")
    _ensure_not_last_admin(db, user, "delete")
    login = user.user_id
    if _has_history(db, user.id):
        user.is_deleted = True
        user.is_active = False
        user.token_version += 1
        user.user_id = f"{login}~deleted~{user.id}"[:80]  # frees the login name for reuse
        mode = "soft"
    else:
        db.delete(user)
        mode = "hard"
    audit_service.log(db, actor=actor, action="USER_DELETED", entity_type="user", entity_id=pk,
                      message=f"Deleted user {login} ({mode} delete)", details={"mode": mode})
    db.commit()
    return mode
