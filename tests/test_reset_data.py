"""scripts/reset_data.py: clear everything except the admin account(s)."""
import importlib.util
import os

import pytest

from tests.conftest import PASSWORD, housekeeping_round, login, make_room, open_ticket

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "reset_data.py")


@pytest.fixture
def reset_tool(tmp_path):
    spec = importlib.util.spec_from_file_location("reset_data", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    cwd = os.getcwd()
    spec.loader.exec_module(mod)
    os.chdir(cwd)
    mod.ROOT = str(tmp_path)  # backups go to a temp folder
    return mod


def _populate(client, team):
    pdf = open(os.path.join(os.path.dirname(__file__), "fixtures", "daily_report.pdf"), "rb").read()
    up = client.post("/api/v1/housekeeping/daily-sheets/upload", headers=team["hk_sup"], files={"file": ("d.pdf", pdf, "application/pdf")})
    assert up.status_code == 200
    t = open_ticket(client, team)
    detail = housekeeping_round(client, team, t["id"], fail=("Shower",))
    repair = detail["repairs"][0]["id"]
    client.post(f"/api/v1/engineering/{repair}/assign", headers=team["admin"], json={"engineer_id": team["eng1_id"]})
    room2 = make_room(client, team["admin"], "102")
    client.post("/api/v1/engineering/repairs", headers=team["admin"], json={"room_id": room2, "reported_defect": "Door lock jams"})
    png = b"\x89PNG\r\n\x1a\n" + b"\x01" * 50
    client.post("/api/v1/uploads", headers=team["eng1"], files={"file": ("x.png", png, "image/png")}, data={"repair_id": str(repair)})
    return t


def _counts():
    from sqlalchemy import text
    from database.connection import engine
    names = ["users", "rooms", "turnover_tickets", "repair_requests", "inspection_sessions", "inspection_results",
             "attachments", "attachment_files", "ticket_assignments", "ticket_activity_logs", "room_types",
             "checklist_templates", "checklist_template_items", "daily_sheets", "daily_sheet_rooms"]
    with engine.connect() as conn:
        return {n: conn.execute(text(f"SELECT COUNT(*) FROM {n}")).scalar() for n in names}


def test_reset_keeps_only_admin_and_app_still_works(client, team, reset_tool):
    _populate(client, team)
    before = _counts()
    assert before["turnover_tickets"] and before["attachments"] and before["users"] == 7  # admin, 2 supervisors, 4 staff
    assert reset_tool.main(["--yes"]) == 0
    after = _counts()
    assert before["daily_sheet_rooms"] == 90
    for t in ["daily_sheets", "daily_sheet_rooms", "rooms", "turnover_tickets", "repair_requests", "inspection_sessions", "inspection_results",
              "attachments", "attachment_files", "ticket_assignments", "ticket_activity_logs"]:
        assert after[t] == 0, t
    assert after["users"] == 1
    assert after["room_types"] == 3 and after["checklist_templates"] == 3 and after["checklist_template_items"] >= 30
    # old session revoked, same password still works
    assert client.get("/api/v1/auth/me", headers=team["admin"]).status_code == 401
    admin = login(client, "FRONT_DESK", "admin", "AdminPass123")
    assert client.get("/api/v1/users", headers=admin).json()["total"] == 1
    # the app works from scratch: new user, room, full turnover
    client.post("/api/v1/users", headers=admin, json={"user_id": "hk.boss", "display_name": "Boss", "role": "HK_SUPERVISOR", "password": PASSWORD})
    boss = login(client, "HOUSEKEEPING", "hk.boss")
    client.post("/api/v1/users", headers=boss, json={"user_id": "hk.new", "display_name": "New", "role": "ROOM_ATTENDANT", "password": PASSWORD})
    hk = login(client, "HOUSEKEEPING", "hk.new")
    hk_id = client.get("/api/v1/users", headers=boss).json()["items"][0]["id"]
    room = make_room(client, admin, "101")
    t = client.post("/api/v1/turnover", headers=admin, json={"room_id": room, "assigned_housekeeper_id": hk_id}).json()
    assert t["ticket_number"].endswith(t["ticket_number"][-5:])
    housekeeping_round(client, {"hk1": hk}, t["id"])
    assert client.post(f"/api/v1/turnover/{t['id']}/release", headers=admin).status_code == 200


def test_reset_can_set_admin_password(client, team, reset_tool, monkeypatch):
    _populate(client, team)
    monkeypatch.setattr(reset_tool.getpass, "getpass", lambda prompt="": "Brand1New2")
    assert reset_tool.main(["--yes", "--set-password", "--no-backup"]) == 0
    r = client.post("/api/v1/auth/login", json={"department": "FRONT_DESK", "user_id": "admin", "password": "AdminPass123"})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"department": "FRONT_DESK", "user_id": "admin", "password": "Brand1New2"})
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is False


def test_keep_setup_keeps_rooms_and_checklists(client, team, reset_tool):
    _populate(client, team)
    assert reset_tool.main(["--yes", "--keep-setup", "--no-backup"]) == 0
    after = _counts()
    assert after["rooms"] == 2 and after["turnover_tickets"] == 0 and after["users"] == 1
    admin = login(client, "FRONT_DESK", "admin", "AdminPass123")
    rooms = client.get("/api/v1/rooms", headers=admin).json()["items"]
    assert all(r["operational_status"] == "READY_FOR_GUEST" and r["occupancy_status"] == "VACANT"
               and r["active_ticket_id"] is None and r["open_repairs"] == 0 for r in rooms)


def test_backup_and_restore_round_trip(client, team, reset_tool, tmp_path):
    _populate(client, team)
    before = _counts()
    assert reset_tool.main(["--yes"]) == 0
    backups = list((tmp_path / "backups").glob("reset-backup-*.json"))
    assert len(backups) == 1
    assert reset_tool.main(["--restore", str(backups[0]), "--yes"]) == 0
    assert _counts() == before
    # restored data works, including the photo bytes
    login(client, "HOUSEKEEPING", "hk.anita")
    admin = login(client, "FRONT_DESK", "admin", "AdminPass123")
    att = client.get("/api/v1/uploads/1", headers=admin)
    assert att.status_code == 200 and att.content == b"\x89PNG\r\n\x1a\n" + b"\x01" * 50


def test_refuses_without_a_front_desk_account_and_on_wrong_confirmation(client, team, reset_tool, monkeypatch):
    before = _counts()
    assert reset_tool.main(["--yes", "--keep-user", "hk.anita"]) == 1
    assert reset_tool.main(["--yes", "--keep-user", "nobody"]) == 1
    monkeypatch.setattr("builtins.input", lambda prompt="": "wrong-name")
    assert reset_tool.main(["--no-backup"]) == 1
    assert _counts() == before


def test_numbering_restarts_after_reset(client, team, reset_tool):
    _populate(client, team)
    open_ticket(client, team, room=make_room(client, team["admin"], "103"))
    assert reset_tool.main(["--yes", "--no-backup"]) == 0
    admin = login(client, "FRONT_DESK", "admin", "AdminPass123")
    room = make_room(client, admin, "101")
    t = client.post("/api/v1/turnover", headers=admin, json={"room_id": room}).json()
    assert t["id"] == 1 and t["ticket_number"].endswith("-00001")
    r = client.post("/api/v1/engineering/repairs", headers=admin, json={"room_id": room, "reported_defect": "Lamp flickers"}).json()
    assert r["repair_number"].endswith("-00001")
