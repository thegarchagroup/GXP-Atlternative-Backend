import logging
import time

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import settings

logger = logging.getLogger("hrm.database")


def _build_engine():
    url = settings.DATABASE_URL
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url.endswith("sqlite://"):
            kwargs["poolclass"] = StaticPool
        eng = create_engine(url, **kwargs)

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return eng
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800, pool_size=10, max_overflow=20)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database(retries: int = 20, delay: float = 3.0) -> None:
    """Wait until the database accepts connections (useful under docker-compose)."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connection established")
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("Database not ready (attempt %s/%s): %s", attempt, retries, exc.__class__.__name__)
            time.sleep(delay)
    raise RuntimeError("Could not connect to the database") from last_error
