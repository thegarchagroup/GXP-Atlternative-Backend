"""Command-line tools.

    python -m migrations.cli migrate
    python -m migrations.cli status
    python -m migrations.cli create-admin --user-id frontdesk.admin --name "Asha Rao"
"""
import argparse
import getpass
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m migrations.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="Apply pending migrations")
    sub.add_parser("status", help="Show pending migrations")
    ca = sub.add_parser("create-admin", help="Create a Front Desk administrator")
    ca.add_argument("--user-id", required=True)
    ca.add_argument("--name", required=True)
    ca.add_argument("--password-env", help="Read the password from this environment variable instead of prompting")
    args = parser.parse_args(argv)

    from database.connection import init_database
    from migrations import startup

    init_database(retries=5, delay=2)
    if args.command == "migrate":
        applied = startup.run_migrations()
        print("Applied: " + (", ".join(applied) if applied else "nothing (up to date)"))
    elif args.command == "status":
        pending = startup.pending_migrations()
        print("Pending: " + (", ".join(pending) if pending else "none"))
    elif args.command == "create-admin":
        startup.run_migrations()
        if args.password_env:
            password = os.environ.get(args.password_env, "")
        else:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Repeat password: "):
                print("Passwords do not match.", file=sys.stderr)
                return 1
        try:
            startup.create_admin(args.user_id, password, args.name)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Administrator '{args.user_id}' created. They will be asked to change the password at first sign-in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
