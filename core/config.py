"""Application settings, read from environment variables.

Nothing sensitive has a default. The process refuses to start without a JWT
secret and database configuration.
"""
import os
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw and raw.strip() else default


class Settings:
    def __init__(self) -> None:
        self.APP_ENV = os.getenv("APP_ENV", "development")
        self.DATABASE_URL = os.getenv("DATABASE_URL") or self._mysql_url()

        self.JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
        if len(self.JWT_SECRET_KEY) < 32:
            raise RuntimeError(
                "JWT_SECRET_KEY must be set to a random string of at least 32 characters. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        self.JWT_ALGORITHM = "HS256"
        self.ACCESS_TOKEN_EXPIRE_MINUTES = _int("ACCESS_TOKEN_EXPIRE_MINUTES", 480)

        self.CORS_ORIGINS = _list("CORS_ORIGINS", "http://localhost:5173")
        self.COOKIE_SECURE = _bool("COOKIE_SECURE", False)
        self.COOKIE_NAME = os.getenv("COOKIE_NAME", "hrm_access_token")
        self.COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax").lower()

        self.HOTEL_TIMEZONE = os.getenv("HOTEL_TIMEZONE", "UTC")
        try:
            ZoneInfo(self.HOTEL_TIMEZONE)
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError(f"HOTEL_TIMEZONE '{self.HOTEL_TIMEZONE}' is not a valid IANA timezone") from exc

        self.UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads"))
        self.MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 8)

        self.AUTO_MIGRATE = _bool("AUTO_MIGRATE", True)
        self.SEED_REFERENCE_DATA = _bool("SEED_REFERENCE_DATA", True)
        self.BOOTSTRAP_ADMIN_USER_ID = os.getenv("BOOTSTRAP_ADMIN_USER_ID", "").strip()
        self.BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
        self.BOOTSTRAP_ADMIN_NAME = os.getenv("BOOTSTRAP_ADMIN_NAME", "Front Desk Administrator")

        # Which departments may perform the final Ready-for-Guest release.
        # Backend rules still apply on top of this (assignment + all checks passed).
        self.RELEASE_DEPARTMENTS = [d.upper() for d in _list("RELEASE_DEPARTMENTS", "FRONT_DESK,HOUSEKEEPING,ENGINEERING")]

        self.BCRYPT_ROUNDS = max(4, min(_int("BCRYPT_ROUNDS", 12), 16))
        self.LOGIN_MAX_ATTEMPTS = _int("LOGIN_MAX_ATTEMPTS", 5)
        self.LOGIN_LOCKOUT_MINUTES = _int("LOGIN_LOCKOUT_MINUTES", 15)

    @staticmethod
    def _mysql_url() -> str:
        host = os.getenv("DB_HOST")
        name = os.getenv("DB_NAME")
        user = os.getenv("DB_USER")
        password = os.getenv("DB_PASSWORD")
        port = os.getenv("DB_PORT", "3306")
        if not all([host, name, user, password]):
            raise RuntimeError(
                "Database is not configured. Set DATABASE_URL, or DB_HOST, DB_PORT, DB_NAME, DB_USER and DB_PASSWORD."
            )
        return f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{name}?charset=utf8mb4"

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


settings = Settings()
