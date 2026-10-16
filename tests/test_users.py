from tests.conftest import PASSWORD, login, make_user


def test_admin_creates_and_deactivates_user(client, admin):
    uid, hk = make_user(client, admin, "HOUSEKEEPING", "hk.one", "Hema")
    r = client.get(f"/api/v1/users/{uid}", headers=admin)
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    assert "password_hash" not in r.json()
    r = client.patch(f"/api/v1/users/{uid}/status", headers=admin, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/api/v1/auth/me", headers=hk).status_code == 401
    r = client.post("/api/v1/auth/login", json={"department": "HOUSEKEEPING", "user_id": "hk.one", "password": PASSWORD})
    assert r.status_code == 401 and r.json()["error"]["code"] == "ACCOUNT_INACTIVE"


def test_non_admin_cannot_manage_users(client, admin):
    _, hk = make_user(client, admin, "HOUSEKEEPING", "hk.one")
    r = client.post("/api/v1/users", headers=hk, json={"user_id": "x.y.z", "display_name": "X", "department": "FRONT_DESK",
                                                       "password": PASSWORD})
    assert r.status_code == 403


def test_duplicate_and_weak_password(client, admin):
    make_user(client, admin, "ENGINEERING", "eng.one")
    r = client.post("/api/v1/users", headers=admin, json={"user_id": "ENG.ONE", "display_name": "Dup",
                                                          "department": "ENGINEERING", "password": PASSWORD})
    assert r.status_code == 409
    r = client.post("/api/v1/users", headers=admin, json={"user_id": "eng.two", "display_name": "Weak",
                                                          "department": "ENGINEERING", "password": "allletters"})
    assert r.status_code == 422


def test_last_admin_protected(client, admin):
    me = client.get("/api/v1/auth/me", headers=admin).json()["user"]
    r = client.patch(f"/api/v1/users/{me['id']}/status", headers=admin, json={"is_active": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "LAST_ADMIN"
    r = client.put(f"/api/v1/users/{me['id']}", headers=admin, json={"department": "HOUSEKEEPING"})
    assert r.status_code == 409
    second_id, _ = make_user(client, admin, "FRONT_DESK", "fd.two")
    r = client.patch(f"/api/v1/users/{second_id}/status", headers=admin, json={"is_active": False})
    assert r.status_code == 200


def test_delete_soft_when_history_hard_when_clean(client, admin):
    r = client.post("/api/v1/users", headers=admin, json={"user_id": "temp.user", "display_name": "Temp",
                                                          "department": "ENGINEERING", "password": PASSWORD})
    clean_id = r.json()["id"]
    r = client.delete(f"/api/v1/users/{clean_id}", headers=admin)
    assert r.status_code == 200 and "deleted" in r.json()["message"].lower()
    assert client.get(f"/api/v1/users/{clean_id}", headers=admin).status_code == 404

    used_id, _ = make_user(client, admin, "ENGINEERING", "eng.used")  # signing in creates history
    r = client.delete(f"/api/v1/users/{used_id}", headers=admin)
    assert r.status_code == 200 and "archived" in r.json()["message"]
    # The login name is released for reuse
    make_user(client, admin, "ENGINEERING", "eng.used")


def test_reset_password_and_filters(client, admin):
    uid, old = make_user(client, admin, "HOUSEKEEPING", "hk.one")
    r = client.post(f"/api/v1/users/{uid}/reset-password", headers=admin, json={"new_password": "Fresh1234"})
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me", headers=old).status_code == 401
    login(client, "HOUSEKEEPING", "hk.one", "Fresh1234")
    r = client.get("/api/v1/users?department=HOUSEKEEPING&search=hk", headers=admin).json()
    assert r["total"] == 1 and r["items"][0]["user_id"] == "hk.one"
