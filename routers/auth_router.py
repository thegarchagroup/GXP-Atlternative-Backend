from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from core.config import settings
from core.dependencies import get_current_user
from database.connection import get_db
from models.user import User
from schemas.auth_schema import ChangePasswordRequest, LoginRequest, LoginResponse, MeResponse
from schemas.common import MessageOut
from schemas.user_schema import UserOut
from services import auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


def _set_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(settings.COOKIE_NAME, token, max_age=max_age, httponly=True, secure=settings.COOKIE_SECURE,
                        samesite=settings.COOKIE_SAMESITE, path="/")


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Sign in with department, user ID and password. Sets an httpOnly session cookie and also
    returns the token for API clients (use it as `Authorization: Bearer <token>`)."""
    user, token, expires_in = auth_service.login(db, body.department, body.user_id, body.password)
    _set_cookie(response, token, expires_in)
    return LoginResponse(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user),
                         hotel_timezone=settings.HOTEL_TIMEZONE)


@router.post("/logout", response_model=MessageOut)
def logout(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    auth_service.logout(db, user)
    response.delete_cookie(settings.COOKIE_NAME, path="/")
    return MessageOut(message="Signed out")


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)):
    return MeResponse(user=UserOut.model_validate(user), hotel_timezone=settings.HOTEL_TIMEZONE)


@router.post("/change-password", response_model=LoginResponse)
def change_password(body: ChangePasswordRequest, response: Response, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    token, expires_in = auth_service.change_password(db, user, body.current_password, body.new_password)
    _set_cookie(response, token, expires_in)
    return LoginResponse(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user),
                         hotel_timezone=settings.HOTEL_TIMEZONE)
