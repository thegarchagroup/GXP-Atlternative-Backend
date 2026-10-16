import re
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from core.config import settings

_hasher = PasswordHash((BcryptHasher(rounds=settings.BCRYPT_ROUNDS),))

PASSWORD_RULES = "at least 8 characters, including a letter and a number (max 72 bytes)"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password, password_hash)
    except Exception:  # malformed hash
        return False


def password_is_strong(password: str) -> bool:
    return (
        len(password) >= 8
        and len(password.encode("utf-8")) <= 72
        and re.search(r"[A-Za-z]", password) is not None
        and re.search(r"\d", password) is not None
    )


def create_access_token(user) -> tuple[str, int]:
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "dept": user.department.value,
        "tv": user.token_version,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM), expires_in


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM], options={"require": ["exp", "sub"]})
