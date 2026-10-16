import threading
import time

from sqlalchemy.orm import Session

from core.config import settings
from core.exceptions import TooManyRequestsError, UnauthorizedError, ValidationFailedError
from core.security import PASSWORD_RULES, create_access_token, hash_password, password_is_strong, verify_password
from database.base import utcnow
from models.enums import Department
from models.user import User
from repositories import user_repository
from services import audit_service

# Simple per-process login throttle (per user id). Use a shared store such as
# Redis if you run several API processes behind a load balancer.
_failures: dict[str, list[float]] = {}
_lock = threading.Lock()
_DUMMY_HASH = hash_password("dummy-password-for-timing-1")


def _check_throttle(key: str) -> None:
    window = settings.LOGIN_LOCKOUT_MINUTES * 60
    now = time.monotonic()
    with _lock:
        attempts = [t for t in _failures.get(key, []) if now - t < window]
        _failures[key] = attempts
        if len(attempts) >= settings.LOGIN_MAX_ATTEMPTS:
            raise TooManyRequestsError(
                f"Too many failed sign-in attempts. Try again in {settings.LOGIN_LOCKOUT_MINUTES} minutes.")


def _record_failure(key: str) -> None:
    with _lock:
        _failures.setdefault(key, []).append(time.monotonic())


def _clear(key: str) -> None:
    with _lock:
        _failures.pop(key, None)


def reset_throttle() -> None:
    with _lock:
        _failures.clear()


def login(db: Session, department: Department, user_id: str, password: str) -> tuple[User, str, int]:
    key = user_id.strip().lower()
    _check_throttle(key)
    user = user_repository.get_by_login(db, user_id)
    if not user or user.is_deleted:
        verify_password(password, _DUMMY_HASH)  # constant-ish timing
        _record_failure(key)
        raise UnauthorizedError("Incorrect user ID or password.", code="INVALID_CREDENTIALS")
    if not verify_password(password, user.password_hash):
        _record_failure(key)
        raise UnauthorizedError("Incorrect user ID or password.", code="INVALID_CREDENTIALS")
    if not user.is_active:
        raise UnauthorizedError("This account has been deactivated. Contact the front desk administrator.",
                                code="ACCOUNT_INACTIVE")
    if user.department != department:
        _record_failure(key)
        raise UnauthorizedError("This account does not belong to the selected department.", code="WRONG_DEPARTMENT")

    _clear(key)
    user.last_login_at = utcnow()
    audit_service.log(db, actor=user, action="AUTH_LOGIN", message=f"{user.display_name} signed in",
                      entity_type="user", entity_id=user.id)
    db.commit()
    token, expires_in = create_access_token(user)
    return user, token, expires_in


def logout(db: Session, user: User) -> None:
    # Invalidate every token issued to this user so far.
    user.token_version += 1
    audit_service.log(db, actor=user, action="AUTH_LOGOUT", message=f"{user.display_name} signed out",
                      entity_type="user", entity_id=user.id)
    db.commit()


def change_password(db: Session, user: User, current_password: str, new_password: str) -> tuple[str, int]:
    if not verify_password(current_password, user.password_hash):
        raise ValidationFailedError("Current password is incorrect.", code="INVALID_CURRENT_PASSWORD")
    if not password_is_strong(new_password):
        raise ValidationFailedError(f"New password must be {PASSWORD_RULES}.", code="WEAK_PASSWORD")
    if verify_password(new_password, user.password_hash):
        raise ValidationFailedError("New password must differ from the current one.", code="PASSWORD_REUSED")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.token_version += 1
    audit_service.log(db, actor=user, action="AUTH_PASSWORD_CHANGED", message=f"{user.display_name} changed their password",
                      entity_type="user", entity_id=user.id)
    db.commit()
    return create_access_token(user)
