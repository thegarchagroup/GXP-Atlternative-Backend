from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

import jwt
from core.config import settings
from core.exceptions import ForbiddenError, UnauthorizedError
from core.security import decode_access_token
from database.connection import get_db
from models.user import User

bearer_scheme = HTTPBearer(auto_error=False, description="JWT from POST /api/v1/auth/login")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Accepts a Bearer token (API clients, Swagger) or the httpOnly session cookie (web app).

    Cookie-authenticated state-changing requests must carry X-Requested-With, which
    browsers cannot add cross-origin without passing the CORS allow-list (CSRF defence).
    """
    token = credentials.credentials if credentials else None
    via_cookie = False
    if not token:
        token = request.cookies.get(settings.COOKIE_NAME)
        via_cookie = token is not None
    if not token:
        raise UnauthorizedError("Authentication required.")
    if via_cookie and request.method in UNSAFE_METHODS and request.headers.get("x-requested-with") != "XMLHttpRequest":
        raise ForbiddenError("Missing X-Requested-With header.", code="CSRF_CHECK_FAILED")

    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Your session has expired. Please sign in again.", code="TOKEN_EXPIRED")
    except jwt.PyJWTError:
        raise UnauthorizedError("Invalid authentication token.", code="TOKEN_INVALID")

    try:
        user_pk = int(payload["sub"])
    except (KeyError, ValueError):
        raise UnauthorizedError("Invalid authentication token.", code="TOKEN_INVALID")

    user = db.get(User, user_pk)
    if not user or user.is_deleted or not user.is_active:
        raise UnauthorizedError("This account is not active.", code="ACCOUNT_INACTIVE")
    if payload.get("tv") != user.token_version or payload.get("dept") != user.department.value:
        raise UnauthorizedError("Your session is no longer valid. Please sign in again.", code="TOKEN_REVOKED")
    return user
