import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="hrm-tests-")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256-0123456789"
os.environ["BOOTSTRAP_ADMIN_USER_ID"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "AdminPass123"
os.environ["UPLOAD_DIR"] = os.path.join(_tmp, "uploads")
os.environ["LOGIN_MAX_ATTEMPTS"] = "5"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PASSWORD = "Passw0rd123"


def _reset_database():
    from sqlalchemy import text

    import models  # noqa: F401
    from database.base import Base
    from database.connection import engine
    from migrations.startup import _meta

    if engine.dialect.name == "sqlite":
        engine.dispose()
        path = engine.url.database
        if path and os.path.exists(path):
            os.remove(path)
    else:
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for table in list(Base.metadata.sorted_tables) + list(_meta.sorted_tables):
                conn.execute(text(f"DROP TABLE IF EXISTS `{table.name}`"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


@pytest.fixture
def client():
    _reset_database()
    _supervisors.clear()
    from services.auth_service import reset_throttle

    reset_throttle()
    import main

    with TestClient(main.app) as c:
        yield c


def login(client, department, user_id, password=PASSWORD):
    r = client.post("/api/v1/auth/login", json={"department": department, "user_id": user_id, "password": password})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin(client):
    return login(client, "FRONT_DESK", "admin", "AdminPass123")


SUPERVISOR_FOR = {"HOUSEKEEPING": "HK_SUPERVISOR", "ENGINEERING": "ENG_SUPERVISOR"}
WORKER_FOR = {"HOUSEKEEPING": "ROOM_ATTENDANT", "ENGINEERING": "TECHNICIAN", "FRONT_DESK": "ADMIN"}
_supervisors: dict = {}


def create_account(client, creator_headers, role, user_id, name=None):
    r = client.post("/api/v1/users", headers=creator_headers, json={
        "user_id": user_id, "display_name": name or user_id.title(), "role": role, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def supervisor(client, admin_headers, department):
    """Headers for the department's supervisor (created on first use in each test)."""
    key = (id(client), department)
    if key not in _supervisors:
        uid = {"HOUSEKEEPING": "hk.sup", "ENGINEERING": "eng.sup"}[department]
        create_account(client, admin_headers, SUPERVISOR_FOR[department], uid, f"{department.title()} Supervisor")
        _supervisors[key] = login(client, department, uid)
    return _supervisors[key]


def make_user(client, admin_headers, department, user_id, name=None, role=None):
    """Create an account the way the app requires: admins and supervisors by Front Desk,
    room attendants by the HK supervisor, technicians by the Engineering supervisor."""
    role = role or WORKER_FOR[department]
    creator = admin_headers if role in ("ADMIN", "HK_SUPERVISOR", "ENG_SUPERVISOR") else supervisor(client, admin_headers, department)
    pk = create_account(client, creator, role, user_id, name)
    return pk, login(client, department, user_id)


def room_type_id(client, headers, name="Standard"):
    types = client.get("/api/v1/rooms/types", headers=headers).json()
    return next(t["id"] for t in types if t["name"] == name)


def make_room(client, headers, number="101", floor=1, type_name="Standard"):
    r = client.post("/api/v1/rooms", headers=headers, json={
        "room_number": number, "floor": floor, "room_type_id": room_type_id(client, headers, type_name)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def team(client, admin):
    hk1_id, hk1 = make_user(client, admin, "HOUSEKEEPING", "hk.anita", "Anita")
    hk2_id, hk2 = make_user(client, admin, "HOUSEKEEPING", "hk.ravi", "Ravi")
    eng1_id, eng1 = make_user(client, admin, "ENGINEERING", "eng.sunil", "Sunil")
    eng2_id, eng2 = make_user(client, admin, "ENGINEERING", "eng.meera", "Meera")
    room = make_room(client, admin)
    return {
        "admin": admin, "hk_sup": supervisor(client, admin, "HOUSEKEEPING"), "eng_sup": supervisor(client, admin, "ENGINEERING"), "hk1": hk1, "hk1_id": hk1_id, "hk2": hk2, "hk2_id": hk2_id,
        "eng1": eng1, "eng1_id": eng1_id, "eng2": eng2, "eng2_id": eng2_id, "room": room,
    }


def open_ticket(client, team, room=None, assign=True, priority="NORMAL"):
    body = {"room_id": room or team["room"], "priority": priority}
    if assign:
        body["assigned_housekeeper_id"] = team["hk1_id"]
    r = client.post("/api/v1/turnover", headers=team["admin"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def checklist_items(client, headers, ticket_id, fail=(), pending=(), na=()):
    data = client.get(f"/api/v1/housekeeping/{ticket_id}/checklist", headers=headers).json()
    items = []
    for res in data["session"]["results"]:
        name = res["item_name"]
        if name in pending:
            continue
        if name in fail:
            items.append({"result_id": res["id"], "result": "FAIL", "remarks": f"{name} is faulty"})
        elif name in na:
            items.append({"result_id": res["id"], "result": "NOT_APPLICABLE"})
        else:
            items.append({"result_id": res["id"], "result": "PASS"})
    return items


def housekeeping_round(client, team, ticket_id, fail=(), headers=None):
    h = headers or team["hk1"]
    r = client.post(f"/api/v1/housekeeping/{ticket_id}/start", headers=h)
    assert r.status_code == 200, r.text
    items = checklist_items(client, h, ticket_id, fail=fail)
    r = client.post(f"/api/v1/housekeeping/{ticket_id}/submit", headers=h, json={"items": items})
    assert r.status_code == 200, r.text
    return r.json()


def engineering_items(client, headers, repair_id, fail=()):
    data = client.get(f"/api/v1/engineering/{repair_id}/checklist", headers=headers).json()
    return [{"result_id": r["id"], "result": "FAIL" if r["item_name"] in fail else "PASS",
             "remarks": "still faulty" if r["item_name"] in fail else None} for r in data["session"]["results"]]


def room_status(client, headers, room_id):
    return client.get(f"/api/v1/rooms/{room_id}", headers=headers).json()["operational_status"]
