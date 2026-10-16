from tests.conftest import PASSWORD, login, make_user


def test_successful_login_returns_token_cookie_and_no_hash(client):
    r = client.post("/api/v1/auth/login", json={"department": "FRONT_DESK", "user_id": "admin", "password": "AdminPass123"})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["user"]["department"] == "FRONT_DESK"
    assert "password_hash" not in body["user"] and "password" not in str(body).lower().replace("must_change_password", "")
    assert "hrm_access_token" in r.headers.get("set-cookie", "")
    assert "httponly" in r.headers["set-cookie"].lower()


def test_invalid_credentials(client):
    r = client.post("/api/v1/auth/login", json={"department": "FRONT_DESK", "user_id": "admin", "password": "wrong-pass1"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    r = client.post("/api/v1/auth/login", json={"department": "FRONT_DESK", "user_id": "nobody", "password": "x"})
    assert r.status_code == 401


def test_wrong_department(client, admin):
    make_user(client, admin, "HOUSEKEEPING", "hk.one")
    r = client.post("/api/v1/auth/login", json={"department": "ENGINEERING", "user_id": "hk.one", "password": PASSWORD})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "WRONG_DEPARTMENT"


def test_login_throttling(client):
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"department": "FRONT_DESK", "user_id": "admin", "password": "bad-pass99"})
    r = client.post("/api/v1/auth/login", json={"department": "FRONT_DESK", "user_id": "admin", "password": "AdminPass123"})
    assert r.status_code == 429


def test_unauthorized_dashboard_access(client, admin):
    _, hk = make_user(client, admin, "HOUSEKEEPING", "hk.one")
    _, eng = make_user(client, admin, "ENGINEERING", "eng.one")
    client.cookies.clear()
    assert client.get("/api/v1/dashboard/frontdesk").status_code == 401
    assert client.get("/api/v1/dashboard/frontdesk", headers=hk).status_code == 403
    assert client.get("/api/v1/dashboard/engineering", headers=hk).status_code == 403
    assert client.get("/api/v1/dashboard/housekeeping", headers=eng).status_code == 403
    assert client.get("/api/v1/users", headers=eng).status_code == 403
    assert client.get("/api/v1/dashboard/housekeeping", headers=hk).status_code == 200
    assert client.get("/api/v1/dashboard/frontdesk", headers=admin).status_code == 200


def test_invalid_and_tampered_tokens(client, admin):
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
    import jwt
    forged = jwt.encode({"sub": "1", "dept": "FRONT_DESK", "tv": 0, "exp": 9999999999}, "wrong-secret-" * 4, algorithm="HS256")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_expired_token(client, admin):
    import jwt
    from core.config import settings
    expired = jwt.encode({"sub": "1", "dept": "FRONT_DESK", "tv": 0, "exp": 1}, settings.JWT_SECRET_KEY, algorithm="HS256")
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_logout_revokes_token(client, admin):
    assert client.get("/api/v1/auth/me", headers=admin).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=admin).status_code == 200
    assert client.get("/api/v1/auth/me", headers=admin).status_code == 401


def test_cookie_auth_requires_csrf_header_for_writes(client):
    r = client.post("/api/v1/auth/login", json={"department": "FRONT_DESK", "user_id": "admin", "password": "AdminPass123"})
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200  # cookie works for reads
    body = {"name": "Penthouse"}
    assert client.post("/api/v1/rooms/types", json=body).status_code == 403
    assert client.post("/api/v1/rooms/types", json=body, headers={"X-Requested-With": "XMLHttpRequest"}).status_code == 201


def test_change_password(client, admin):
    r = client.post("/api/v1/auth/change-password", headers=admin,
                    json={"current_password": "AdminPass123", "new_password": "NewAdmin456"})
    assert r.status_code == 200
    assert r.json()["user"]["must_change_password"] is False
    assert client.get("/api/v1/auth/me", headers=admin).status_code == 401  # old token revoked
    login(client, "FRONT_DESK", "admin", "NewAdmin456")
    r = client.post("/api/v1/auth/change-password", headers={"Authorization": f"Bearer {r.json()['access_token']}"},
                    json={"current_password": "NewAdmin456", "new_password": "short"})
    assert r.status_code == 422


def test_health_and_docs_public(client):
    assert client.get("/health").json() == {"status": "healthy"}
    assert client.get("/docs").status_code == 200
