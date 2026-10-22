"""Versioned, idempotent schema migrations and startup tasks.

Each migration runs once and is recorded in `schema_migrations`. Nothing is ever
dropped. To change the schema later, append a new (id, function) pair to
MIGRATIONS that issues the needed ALTER statements; never edit an applied one.

Run explicitly with:  python -m migrations.cli migrate
Startup runs pending migrations automatically when AUTO_MIGRATE=true.
"""
import logging

from sqlalchemy import Column, DateTime, MetaData, String, Table, inspect, select
from sqlalchemy.orm import Session

import models  # noqa: F401  (registers all tables)
from core.config import settings
from core.security import hash_password, password_is_strong
from database.base import Base, utcnow
from database.connection import SessionLocal, engine
from migrations import seed_data

logger = logging.getLogger("hrm.migrations")

_meta = MetaData()
schema_migrations = Table(
    "schema_migrations", _meta,
    Column("id", String(100), primary_key=True),
    Column("applied_at", DateTime, nullable=False),
)


def _m0001_initial_schema(conn) -> None:
    # create_all only creates missing tables; it never drops or alters existing ones.
    Base.metadata.create_all(bind=conn)


def _m0002_seed_reference_data(conn) -> None:
    if not settings.SEED_REFERENCE_DATA:
        return
    from models.checklist import ChecklistTemplate, ChecklistTemplateItem
    from models.enums import CHECKLIST_DEPARTMENT, ChecklistType
    from models.room import RoomType

    with Session(bind=conn) as db:
        if not db.scalar(select(RoomType.id).limit(1)):
            for name, category, desc in seed_data.ROOM_TYPES:
                db.add(RoomType(name=name, category=category, description=desc))
        if not db.scalar(select(ChecklistTemplate.id).limit(1)):
            for ctype, title, items in (
                (ChecklistType.HOUSEKEEPING_CLEANING, "Cleaning", seed_data.HOUSEKEEPING_CLEANING),
                (ChecklistType.HOUSEKEEPING_INSPECTION, "Engineering items", seed_data.HOUSEKEEPING_INSPECTION),
                (ChecklistType.ENGINEERING_INSPECTION, "Engineering verification", seed_data.ENGINEERING_INSPECTION),
            ):
                tpl = ChecklistTemplate(name=title, checklist_type=ctype, department=CHECKLIST_DEPARTMENT[ctype])
                db.add(tpl)
                db.flush()
                for order, (name, category, mandatory, allow_na) in enumerate(items, start=1):
                    db.add(ChecklistTemplateItem(template_id=tpl.id, name=name, category=category,
                                                 is_mandatory=mandatory, allow_not_applicable=allow_na,
                                                 display_order=order * 10, room_type_ids=[]))
        db.flush()


def _sqlite_rebuild(conn, table_name: str) -> None:
    """SQLite cannot change a column's NULL constraint in place. Follows SQLite's documented
    procedure: foreign keys off, create the new table under a temporary name, copy rows,
    drop the old table, rename the new one, then verify foreign keys."""
    from sqlalchemy.schema import CreateTable

    table = Base.metadata.tables[table_name]
    tmp_name = f"_new_{table_name}"
    conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if conn.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
        raise RuntimeError("Could not disable SQLite foreign keys for the table rebuild; nothing was changed.")
    conn.exec_driver_sql("PRAGMA legacy_alter_table=ON")
    try:
        # the old table's indexes are recreated by the new table definition
        for (index_name,) in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                (table_name,)).fetchall():
            conn.exec_driver_sql(f'DROP INDEX "{index_name}"')
        ddl = str(CreateTable(table).compile(dialect=conn.dialect)).strip()
        prefix = f"CREATE TABLE {table_name} ("
        if not ddl.startswith(prefix):
            raise RuntimeError(f"Unexpected DDL for {table_name}; nothing was changed.")
        conn.exec_driver_sql(f'CREATE TABLE "{tmp_name}" (' + ddl[len(prefix):])
        old_cols = {row[1] for row in conn.exec_driver_sql(f'PRAGMA table_info("{table_name}")').fetchall()}
        cols = ", ".join(f'"{c.name}"' for c in table.columns if c.name in old_cols)
        conn.exec_driver_sql(f'INSERT INTO "{tmp_name}" ({cols}) SELECT {cols} FROM "{table_name}"')
        conn.exec_driver_sql(f'DROP TABLE "{table_name}"')
        conn.exec_driver_sql(f'ALTER TABLE "{tmp_name}" RENAME TO "{table_name}"')
        for index in table.indexes:
            index.create(bind=conn)
        problems = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise RuntimeError(f"Foreign key check failed after rebuilding {table_name}: {problems[:5]}")
    finally:
        conn.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def _sqlite_backup(conn, label: str) -> None:
    """Copy the SQLite database file before a structural change (SQLite DDL is not transactional)."""
    path = conn.engine.url.database
    if not path or path == ":memory:":
        return
    import os
    backup = f"{path}.before-{label}.bak"
    if not os.path.exists(backup):
        conn.exec_driver_sql(f"VACUUM INTO '{backup}'")
        logger.warning("Backed up the database to %s before migration %s", backup, label)


def _m0003_direct_repairs(conn) -> None:
    """Front desk can raise repairs that are not part of a turnover ticket:
    repair_requests.ticket_id and inspection_sessions.ticket_id become nullable,
    ticket_assignments.ticket_id becomes nullable, and repair_requests gets blocks_room. Safe on databases created by 0001 with the new model."""
    insp = inspect(conn)
    repair_cols = {c["name"]: c for c in insp.get_columns("repair_requests")}
    session_cols = {c["name"]: c for c in insp.get_columns("inspection_sessions")}
    assign_cols = {c["name"]: c for c in insp.get_columns("ticket_assignments")}
    needs_change = (not repair_cols["ticket_id"]["nullable"] or not session_cols["ticket_id"]["nullable"]
                    or not assign_cols["ticket_id"]["nullable"] or "blocks_room" not in repair_cols)
    if not needs_change:
        return
    if conn.dialect.name == "sqlite":
        _sqlite_backup(conn, "0003")
        if "blocks_room" not in repair_cols:
            conn.exec_driver_sql("ALTER TABLE repair_requests ADD COLUMN blocks_room BOOLEAN NOT NULL DEFAULT 0")
        _sqlite_rebuild(conn, "repair_requests")
        _sqlite_rebuild(conn, "inspection_sessions")
        _sqlite_rebuild(conn, "ticket_assignments")
        return
    # MySQL / MariaDB
    if not repair_cols["ticket_id"]["nullable"]:
        conn.exec_driver_sql("ALTER TABLE repair_requests MODIFY ticket_id INTEGER NULL")
    if not session_cols["ticket_id"]["nullable"]:
        conn.exec_driver_sql("ALTER TABLE inspection_sessions MODIFY ticket_id INTEGER NULL")
    if not assign_cols["ticket_id"]["nullable"]:
        conn.exec_driver_sql("ALTER TABLE ticket_assignments MODIFY ticket_id INTEGER NULL")
    if "blocks_room" not in repair_cols:
        conn.exec_driver_sql("ALTER TABLE repair_requests ADD COLUMN blocks_room BOOLEAN NOT NULL DEFAULT 0")


def _m0004_attachment_files(conn) -> None:
    """Uploaded files are stored in the database (table attachment_files)."""
    from models.inspection import AttachmentFile

    AttachmentFile.__table__.create(bind=conn, checkfirst=True)


def _m0005_user_roles(conn) -> None:
    """Accounts get a role inside their department. Existing accounts: Front Desk -> ADMIN,
    Housekeeping -> ROOM_ATTENDANT, Engineering -> TECHNICIAN."""
    cols = {c["name"] for c in inspect(conn).get_columns("users")}
    if "role" not in cols:
        conn.exec_driver_sql("ALTER TABLE users ADD COLUMN role VARCHAR(40) NOT NULL DEFAULT 'ADMIN'")
        conn.exec_driver_sql("CREATE INDEX ix_users_role ON users (role)")
    conn.exec_driver_sql("UPDATE users SET role='ROOM_ATTENDANT' WHERE department='HOUSEKEEPING' AND role='ADMIN'")
    conn.exec_driver_sql("UPDATE users SET role='TECHNICIAN' WHERE department='ENGINEERING' AND role='ADMIN'")


def _m0006_daily_sheets(conn) -> None:
    """Daily housekeeping task sheets (uploaded PDF), their rooms, and the link from a form to its room."""
    from models.daily_sheet import DailySheet, DailySheetRoom

    DailySheet.__table__.create(bind=conn, checkfirst=True)
    DailySheetRoom.__table__.create(bind=conn, checkfirst=True)
    cols = {c["name"] for c in inspect(conn).get_columns("inspection_sessions")}
    if "daily_room_id" not in cols:
        conn.exec_driver_sql("ALTER TABLE inspection_sessions ADD COLUMN daily_room_id INTEGER NULL")
        conn.exec_driver_sql("CREATE INDEX ix_inspection_sessions_daily_room_id ON inspection_sessions (daily_room_id)")


def _m0007_requests_and_pending(conn) -> None:
    """Front desk guest requests, and "not doable now" (pending) repairs."""
    from models.guest_request import GuestRequest

    GuestRequest.__table__.create(bind=conn, checkfirst=True)
    cols = {c["name"] for c in inspect(conn).get_columns("repair_requests")}
    new_cols = [
        ("pending_reason", "VARCHAR(40) NULL"), ("pending_note", "TEXT NULL"), ("expected_date", "DATE NULL"),
        ("pending_since", "DATETIME NULL"), ("room_sellable", "BOOLEAN NOT NULL DEFAULT 1"),
        ("escalated", "BOOLEAN NOT NULL DEFAULT 0"), ("escalation_note", "TEXT NULL"),
    ]
    for name, ddl in new_cols:
        if name not in cols:
            conn.exec_driver_sql(f"ALTER TABLE repair_requests ADD COLUMN {name} {ddl}")


MIGRATIONS = [
    ("0001_initial_schema", _m0001_initial_schema),
    ("0002_seed_reference_data", _m0002_seed_reference_data),
    ("0003_direct_repairs", _m0003_direct_repairs),
    ("0004_attachment_files", _m0004_attachment_files),
    ("0005_user_roles", _m0005_user_roles),
    ("0006_daily_sheets", _m0006_daily_sheets),
    ("0007_requests_and_pending", _m0007_requests_and_pending),
]


def import_disk_uploads() -> None:
    """Move photos saved by older versions (in UPLOAD_DIR) into the database."""
    from services.upload_service import import_files_from_disk

    with SessionLocal() as db:
        imported, missing = import_files_from_disk(db)
    if imported:
        logger.warning("Copied %s uploaded file(s) from %s into the database. The originals were left in place.",
                       imported, settings.UPLOAD_DIR)
    if missing:
        logger.warning("%s uploaded file(s) are not in the database and not in %s on this computer "
                       "(start the backend once on the computer that has them to copy them in).", missing, settings.UPLOAD_DIR)


def run_migrations() -> list[str]:
    applied_now = []
    with engine.begin() as conn:
        _meta.create_all(bind=conn)
        done = {row[0] for row in conn.execute(select(schema_migrations.c.id))}
    for mig_id, fn in MIGRATIONS:
        if mig_id in done:
            continue
        with engine.begin() as conn:
            logger.info("Applying migration %s", mig_id)
            fn(conn)
            conn.execute(schema_migrations.insert().values(id=mig_id, applied_at=utcnow()))
        applied_now.append(mig_id)
    return applied_now


def pending_migrations() -> list[str]:
    if not inspect(engine).has_table("schema_migrations"):
        return [m for m, _ in MIGRATIONS]
    with engine.connect() as conn:
        done = {row[0] for row in conn.execute(select(schema_migrations.c.id))}
    return [m for m, _ in MIGRATIONS if m not in done]


def create_admin(user_id: str, password: str, display_name: str, *, must_change: bool = True) -> str:
    from models.enums import Department, Role
    from models.user import User
    from repositories import user_repository

    if not password_is_strong(password):
        raise ValueError("Password must be at least 8 characters with a letter and a number (max 72 bytes).")
    with SessionLocal() as db:
        if user_repository.get_by_login(db, user_id):
            raise ValueError(f"User ID '{user_id}' already exists.")
        db.add(User(user_id=user_id, display_name=display_name, department=Department.FRONT_DESK, role=Role.ADMIN,
                    password_hash=hash_password(password), must_change_password=must_change))
        db.commit()
    return user_id


def bootstrap_admin_from_env() -> None:
    """Create the first administrator from BOOTSTRAP_ADMIN_* only when no active admin exists."""
    if not (settings.BOOTSTRAP_ADMIN_USER_ID and settings.BOOTSTRAP_ADMIN_PASSWORD):
        return
    from repositories import user_repository

    with SessionLocal() as db:
        if user_repository.count_active_admins(db) > 0:
            return
        if user_repository.get_by_login(db, settings.BOOTSTRAP_ADMIN_USER_ID):
            logger.warning("Bootstrap admin user ID already exists but is not an active admin; skipping.")
            return
    try:
        create_admin(settings.BOOTSTRAP_ADMIN_USER_ID, settings.BOOTSTRAP_ADMIN_PASSWORD, settings.BOOTSTRAP_ADMIN_NAME)
        logger.warning("Created bootstrap administrator '%s'. Remove BOOTSTRAP_ADMIN_PASSWORD from the environment "
                       "and change the password after first sign-in.", settings.BOOTSTRAP_ADMIN_USER_ID)
    except ValueError as exc:
        logger.error("Bootstrap administrator not created: %s", exc)


def run_startup_tasks() -> None:
    if settings.AUTO_MIGRATE:
        applied = run_migrations()
        if applied:
            logger.info("Applied migrations: %s", ", ".join(applied))
    else:
        pending = pending_migrations()
        if pending:
            raise RuntimeError(f"Pending migrations {pending}. Run: python -m migrations.cli migrate")
    import_disk_uploads()
    bootstrap_admin_from_env()
