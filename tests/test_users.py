"""Account management by role:
Front Desk admins manage admins and supervisors; HK supervisors manage room attendants;
Engineering supervisors manage technicians."""
from tests.conftest import PASSWORD, create_account, login, make_user


def body(uid, role, **extra):
    return {"user_id": uid, "display_name": uid.title(), "role": role, "password": PASSWORD, **extra}


def test_front_desk_creates_supervisors_not_staff(client, admin):
    r = client.post("/api/v1/users", headers=admin, json=body("hk.boss", "HK_SUPERVISOR"))
    assert r.status_code == 201 and r.json()["role"] == "HK_SUPERVISOR" and r.json()["department"] == "HOUSEKEEPING"
    r = client.post("/api/v1/users", headers=admin, json=body("eng.boss", "ENG_SUPERVISOR"))
    assert r.status_code == 201 and r.json()["department"] == "ENGINEERING"
    assert client.post("/api/v1/users", headers=admin, json=body("fd.two", "ADMIN")).status_code == 201
    for role in ("ROOM_ATTENDANT", "TECHNICIAN"):
        r = client.post("/api/v1/users", headers=admin, json=body(f"x.{role.lower()}", role))
        assert r.status_code == 403 and r.json()["error"]["code"] == "ROLE_NOT_ALLOWED"
    roles = sorted(u["role"] for u in client.get("/api/v1/users", headers=admin).json()["items"])
    assert roles == ["ADMIN", "ADMIN", "ENG_SUPERVISOR", "HK_SUPERVISOR"]


def test_hk_supervisor_manages_room_attendants_only(client, admin):
    create_account(client, admin, "HK_SUPERVISOR", "hk.boss")
    boss = login(client, "HOUSEKEEPING", "hk.boss")
    r = client.post("/api/v1/users", headers=boss, json=body("ra.anita", "ROOM_ATTENDANT"))
    assert r.status_code == 201 and r.json()["department"] == "HOUSEKEEPING"
    ra_id = r.json()["id"]
    for role in ("TECHNICIAN", "HK_SUPERVISOR", "ADMIN"):
        assert client.post("/api/v1/users", headers=boss, json=body(f"x.{role.lower()}", role)).status_code == 403
    # sees only room attendants
    assert [u["user_id"] for u in client.get("/api/v1/users", headers=boss).json()["items"]] == ["ra.anita"]
    admin_id = client.get("/api/v1/auth/me", headers=admin).json()["user"]["id"]
    assert client.get(f"/api/v1/users/{admin_id}", headers=boss).status_code == 404
    assert client.patch(f"/api/v1/users/{admin_id}/status", headers=boss, json={"is_active": False}).status_code == 404
    # deactivate, reset password, delete own team
    ra = login(client, "HOUSEKEEPING", "ra.anita")
    assert client.post(f"/api/v1/users/{ra_id}/reset-password", headers=boss, json={"new_password": "Fresh1234"}).status_code == 200
    assert client.get("/api/v1/auth/me", headers=ra).status_code == 401
    assert client.patch(f"/api/v1/users/{ra_id}/status", headers=boss, json={"is_active": False}).json()["is_active"] is False
    assert client.delete(f"/api/v1/users/{ra_id}", headers=boss).status_code == 200


def test_eng_supervisor_manages_technicians_only(client, admin):
    create_account(client, admin, "ENG_SUPERVISOR", "eng.boss")
    boss = login(client, "ENGINEERING", "eng.boss")
    assert client.post("/api/v1/users", headers=boss, json=body("tech.sunil", "TECHNICIAN")).status_code == 201
    assert client.post("/api/v1/users", headers=boss, json=body("x.ra", "ROOM_ATTENDANT")).status_code == 403
    assert [u["role"] for u in client.get("/api/v1/users", headers=boss).json()["items"]] == ["TECHNICIAN"]


def test_staff_cannot_manage_accounts(client, admin):
    _, ra = make_user(client, admin, "HOUSEKEEPING", "ra.one")
    _, tech = make_user(client, admin, "ENGINEERING", "tech.one")
    for h in (ra, tech):
        assert client.get("/api/v1/users", headers=h).status_code == 403
        assert client.post("/api/v1/users", headers=h, json=body("x.y", "ROOM_ATTENDANT")).status_code == 403


def test_login_shows_role_and_department_must_match(client, admin):
    create_account(client, admin, "HK_SUPERVISOR", "hk.boss")
    r = client.post("/api/v1/auth/login", json={"department": "HOUSEKEEPING", "user_id": "hk.boss", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["role"] == "HK_SUPERVISOR"
    r = client.post("/api/v1/auth/login", json={"department": "ENGINEERING", "user_id": "hk.boss", "password": PASSWORD})
    assert r.status_code == 401 and r.json()["error"]["code"] == "WRONG_DEPARTMENT"


def test_role_change_signs_user_out(client, admin):
    pk = create_account(client, admin, "HK_SUPERVISOR", "hk.boss")
    boss = login(client, "HOUSEKEEPING", "hk.boss")
    r = client.put(f"/api/v1/users/{pk}", headers=admin, json={"role": "ENG_SUPERVISOR"})
    assert r.status_code == 200 and r.json()["department"] == "ENGINEERING"
    assert client.get("/api/v1/auth/me", headers=boss).status_code == 401
    login(client, "ENGINEERING", "hk.boss")


def test_last_admin_and_password_rules(client, admin):
    me = client.get("/api/v1/auth/me", headers=admin).json()["user"]
    assert client.patch(f"/api/v1/users/{me['id']}/status", headers=admin, json={"is_active": False}).json()["error"]["code"] == "LAST_ADMIN"
    assert client.put(f"/api/v1/users/{me['id']}", headers=admin, json={"role": "HK_SUPERVISOR"}).status_code == 409
    r = client.post("/api/v1/users", headers=admin, json=body("weak.one", "HK_SUPERVISOR", password="allletters"))
    assert r.status_code == 422
    create_account(client, admin, "HK_SUPERVISOR", "dup.one")
    assert client.post("/api/v1/users", headers=admin, json=body("DUP.ONE", "ENG_SUPERVISOR")).status_code == 409
    assert "password_hash" not in client.get(f"/api/v1/users/{me['id']}", headers=admin).json()


def test_delete_soft_when_history_hard_when_clean(client, admin):
    clean = create_account(client, admin, "ENG_SUPERVISOR", "temp.boss")
    r = client.delete(f"/api/v1/users/{clean}", headers=admin)
    assert r.status_code == 200 and "deleted" in r.json()["message"].lower()
    used, _ = make_user(client, admin, "FRONT_DESK", "fd.used", role="ADMIN")  # signing in creates history
    r = client.delete(f"/api/v1/users/{used}", headers=admin)
    assert r.status_code == 200 and "archived" in r.json()["message"]
    make_user(client, admin, "FRONT_DESK", "fd.used", role="ADMIN")  # login name is free again


def test_legacy_department_only_request_still_works(client, admin):
    """Older clients that send a department instead of a role get the role this manager may create."""
    r = client.post("/api/v1/users", headers=admin, json={"user_id": "fd.legacy", "display_name": "L",
                                                          "department": "FRONT_DESK", "password": PASSWORD})
    assert r.status_code == 201 and r.json()["role"] == "ADMIN"
