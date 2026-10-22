"""Clear the database except the Front Desk admin account(s).

Run from the backend folder, with the virtual environment active (and the SSH tunnel open
if DATABASE_URL points at the server):

    python scripts/reset_data.py                      # keep all Front Desk accounts
    python scripts/reset_data.py --keep-user admin    # keep only "admin"
    python scripts/reset_data.py --set-password       # also choose a new password for the kept account(s)
    python scripts/reset_data.py --keep-setup         # also keep rooms, room types and checklists

    python scripts/reset_data.py --restore backups/reset-backup-YYYYMMDD-HHMMSS.json

What it does, in one transaction (all or nothing):
  * saves a full backup of every table to backups/ (unless --no-backup)
  * deletes daily task sheets, tickets, repairs, inspections, photos, assignments and the activity log
  * deletes every user except the kept account(s)
  * deletes rooms, and resets room types and checklists to the defaults (unless --keep-setup)
  * signs the kept account(s) out of existing sessions

The database it clears is the one in .env (DATABASE_URL). Stop the backend before running it.
"""
import argparse
import base64
import getpass
import json
import os
import sys
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import Boolean, Date, DateTime, LargeBinary, select, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

import models  # noqa: E402,F401  (registers every table)
from core.config import settings  # noqa: E402
from core.security import PASSWORD_RULES, hash_password, password_is_strong  # noqa: E402
from database.base import Base  # noqa: E402
from database.connection import engine, init_database  # noqa: E402
from migrations import startup  # noqa: E402
from models.enums import Department  # noqa: E402
from models.user import User  # noqa: E402

# Cleared in every reset (order does not matter: foreign key checks are paused).
ACTIVITY_TABLES = [
    "guest_requests", "daily_sheet_rooms", "daily_sheets", "attachment_files", "attachments", "inspection_results", "inspection_sessions", "ticket_assignments",
    "repair_requests", "ticket_activity_logs", "turnover_tickets",
]
SETUP_TABLES = ["rooms", "checklist_template_items", "checklist_templates", "room_types"]


def describe_database() -> str:
    url = make_url(settings.DATABASE_URL)
    if url.get_backend_name() == "sqlite":
        return f"SQLite file {url.database}"
    return f"MySQL database '{url.database}' on {url.host}:{url.port or 3306}"


def database_name() -> str:
    url = make_url(settings.DATABASE_URL)
    return os.path.basename(url.database) if url.get_backend_name() == "sqlite" else url.database


def existing_tables(conn) -> list[str]:
    from sqlalchemy import inspect
    present = set(inspect(conn).get_table_names())
    return [t.name for t in Base.metadata.sorted_tables if t.name in present]


class foreign_keys_paused:
    """Pause foreign key checks (needed because some tables reference each other)."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        if self.conn.dialect.name == "sqlite":
            self.conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        else:
            self.conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
        return self

    def __exit__(self, *exc):
        if self.conn.dialect.name == "sqlite":
            self.conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        else:
            self.conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")
        return False


# --------------------------------------------------------------------------- backup / restore

def _encode(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__b64__": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _decode(column, value):
    if value is None:
        return None
    if isinstance(value, dict) and "__b64__" in value:
        return base64.b64decode(value["__b64__"])
    if isinstance(column.type, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(column.type, Date):
        return date.fromisoformat(value)
    if isinstance(column.type, Boolean):
        return bool(value)
    if isinstance(column.type, LargeBinary) and isinstance(value, str):
        return base64.b64decode(value)
    return value


def backup(conn) -> str:
    os.makedirs(os.path.join(ROOT, "backups"), exist_ok=True)
    path = os.path.join(ROOT, "backups", f"reset-backup-{datetime.now():%Y%m%d-%H%M%S}.json")
    data = {"database": describe_database(), "created_at": datetime.now().isoformat(), "tables": {}}
    for name in existing_tables(conn):
        table = Base.metadata.tables[name]
        rows = conn.execute(select(table)).mappings().all()
        data["tables"][name] = [{k: _encode(v) for k, v in row.items()} for row in rows]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    total = sum(len(v) for v in data["tables"].values())
    print(f"Backup saved: {path}  ({total} rows)")
    return path


def restore(path: str, assume_yes: bool) -> int:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    print(f"Restore {path}")
    print(f"  taken from: {data.get('database')} at {data.get('created_at')}")
    print(f"  into:       {describe_database()}")
    print("  This replaces ALL current data with the backup.")
    if not assume_yes and not confirm():
        return 1
    with engine.begin() as conn:
        present = existing_tables(conn)
        with foreign_keys_paused(conn):
            for name in present:
                conn.execute(Base.metadata.tables[name].delete())
            restored = 0
            for name in present:
                rows = data["tables"].get(name, [])
                if not rows:
                    continue
                table = Base.metadata.tables[name]
                cols = {c.name: c for c in table.columns}
                clean = [{k: _decode(cols[k], v) for k, v in row.items() if k in cols} for row in rows]
                conn.execute(table.insert(), clean)
                restored += len(clean)
    print(f"Restored {restored} rows. Start the backend again.")
    return 0


# --------------------------------------------------------------------------- reset

def confirm() -> bool:
    expected = database_name()
    answer = input(f"Type the database name ({expected}) to continue, or press Enter to cancel: ").strip()
    if answer != expected:
        print("Cancelled. Nothing was changed.")
        return False
    return True


def ask_password() -> str:
    while True:
        pw = getpass.getpass("New password for the kept account(s): ")
        if not password_is_strong(pw):
            print(f"  Password must be {PASSWORD_RULES}.")
            continue
        if pw != getpass.getpass("Repeat the password: "):
            print("  Passwords do not match.")
            continue
        return pw


def reset(args) -> int:
    with engine.connect() as conn:
        users = conn.execute(select(User.__table__.c.id, User.__table__.c.user_id, User.__table__.c.department,
                                    User.__table__.c.is_deleted)).all()
    live = [u for u in users if not u.is_deleted]
    if args.keep_user:
        wanted = {u.lower() for u in args.keep_user}
        keep = [u for u in live if u.user_id.lower() in wanted]
        missing = wanted - {u.user_id.lower() for u in keep}
        if missing:
            print(f"These user IDs were not found: {', '.join(sorted(missing))}. Nothing was changed.")
            return 1
        if not any(u.department == Department.FRONT_DESK for u in keep):
            print("Keep at least one Front Desk account, otherwise nobody can sign in. Nothing was changed.")
            return 1
    else:
        keep = [u for u in live if u.department == Department.FRONT_DESK]
        if not keep:
            print("No Front Desk account found. Create one first: python -m migrations.cli create-admin ...")
            return 1

    keep_ids = [u.id for u in keep]
    print(f"Database: {describe_database()}")
    print(f"Keeping:  {', '.join(u.user_id for u in keep)}" + ("  (new password will be set)" if args.set_password else ""))
    print("Deleting: tickets, repairs, inspections, photos, assignments, activity log, "
          f"{len(live) - len(keep)} other user(s)" + ("" if args.keep_setup else ", rooms"))
    print("Keeping:  rooms, room types and checklists" if args.keep_setup
          else "Resetting: room types and checklists to the defaults")
    if make_url(settings.DATABASE_URL).get_backend_name() != "sqlite":
        print("Note: the local app and the server use this same database, so this clears it for both.")
    if not args.yes and not confirm():
        return 1
    new_password = ask_password() if args.set_password else None

    with engine.begin() as conn:
        if not args.no_backup:
            backup(conn)
        present = set(existing_tables(conn))
        with foreign_keys_paused(conn):
            for name in ACTIVITY_TABLES:
                if name in present:
                    conn.execute(Base.metadata.tables[name].delete())
            if args.keep_setup:
                tpl = Base.metadata.tables["checklist_templates"]
                conn.execute(tpl.update().where(tpl.c.created_by_id.not_in(keep_ids)).values(created_by_id=None))
                conn.execute(text(
                    "UPDATE rooms SET active_ticket_id=NULL, assigned_housekeeper_id=NULL, assigned_engineer_id=NULL, "
                    "operational_status='READY_FOR_GUEST', occupancy_status='VACANT', last_inspection_at=NULL"))
            else:
                for name in SETUP_TABLES:
                    conn.execute(Base.metadata.tables[name].delete())
            users_t = User.__table__
            conn.execute(users_t.delete().where(users_t.c.id.not_in(keep_ids)))
            values = {"created_by_id": None, "token_version": users_t.c.token_version + 1, "is_active": True}
            if new_password:
                values.update(password_hash=hash_password(new_password), must_change_password=False)
            conn.execute(users_t.update().where(users_t.c.id.in_(keep_ids)).values(**values))
        if not args.keep_setup:
            startup._m0002_seed_reference_data(conn)

    restart_numbering(ACTIVITY_TABLES + ([] if args.keep_setup else SETUP_TABLES) + ["users"])
    print("Done. The database is cleared. Start the backend and sign in as: " + ", ".join(u.user_id for u in keep))
    if new_password:
        print("Use the new password you just set.")
    return 0


def restart_numbering(tables: list[str]) -> None:
    """Start ticket and repair numbers from 00001 again. MySQL keeps counting after rows are
    deleted, so its counters are reset (it never goes below the highest remaining id).
    SQLite already restarts after the highest remaining id."""
    if engine.dialect.name != "mysql":
        return
    with engine.begin() as conn:
        present = set(existing_tables(conn))
        for name in tables:
            if name in present:
                conn.exec_driver_sql(f"ALTER TABLE `{name}` AUTO_INCREMENT = 1")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/reset_data.py",
                                     description="Clear the database except the Front Desk admin account(s).")
    parser.add_argument("--keep-user", action="append", metavar="USER_ID",
                        help="user ID to keep (repeat for several). Default: every Front Desk account")
    parser.add_argument("--set-password", action="store_true", help="choose a new password for the kept account(s)")
    parser.add_argument("--keep-setup", action="store_true", help="keep rooms, room types and checklists")
    parser.add_argument("--no-backup", action="store_true", help="skip the backup file")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--restore", metavar="BACKUP_FILE", help="put back the data from a backup file")
    args = parser.parse_args(argv)

    init_database(retries=3, delay=2)
    startup.run_migrations()  # make sure every table exists before touching data
    if args.restore:
        return restore(args.restore, args.yes)
    return reset(args)


if __name__ == "__main__":
    sys.exit(main())
