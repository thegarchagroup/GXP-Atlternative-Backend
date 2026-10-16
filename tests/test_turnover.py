from tests.conftest import make_room, open_ticket, room_status


def test_ticket_creation_sets_room_state(client, team):
    client.patch(f"/api/v1/rooms/{team['room']}/occupancy", headers=team["admin"], json={"occupancy_status": "OCCUPIED"})
    r = client.post("/api/v1/turnover", headers=team["admin"], json={"room_id": team["room"], "priority": "HIGH"})
    assert r.status_code == 201
    t = r.json()
    assert t["ticket_number"].startswith("TT-") and t["status"] == "AWAITING_HOUSEKEEPING"
    room = client.get(f"/api/v1/rooms/{team['room']}", headers=team["admin"]).json()
    assert room["operational_status"] == "AWAITING_HOUSEKEEPING" and room["occupancy_status"] == "VACANT"
    assert room["active_ticket_id"] == t["id"]
    assert t["readiness"]["ready"] is False

    r = client.post(f"/api/v1/turnover/{t['id']}/assign", headers=team["admin"], json={"housekeeper_id": team["hk1_id"]})
    assert r.json()["status"] == "HOUSEKEEPING_ASSIGNED"
    assert room_status(client, team["admin"], team["room"]) == "HOUSEKEEPING_ASSIGNED"
    mine = client.get("/api/v1/housekeeping/my-tickets", headers=team["hk1"]).json()
    assert [x["id"] for x in mine] == [t["id"]]


def test_duplicate_active_ticket_prevention_and_exception(client, team):
    open_ticket(client, team)
    r = client.post("/api/v1/turnover", headers=team["admin"], json={"room_id": team["room"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_ACTIVE_TICKET"
    r = client.post("/api/v1/turnover", headers=team["admin"], json={"room_id": team["room"], "allow_duplicate": True})
    assert r.status_code == 422
    r = client.post("/api/v1/turnover", headers=team["admin"],
                    json={"room_id": team["room"], "allow_duplicate": True, "duplicate_reason": "Room move mid-stay"})
    assert r.status_code == 201 and r.json()["is_exception"] is True


def test_only_admin_creates_and_assigns(client, team):
    r = client.post("/api/v1/turnover", headers=team["hk1"], json={"room_id": team["room"]})
    assert r.status_code == 403
    t = open_ticket(client, team, assign=False)
    r = client.post(f"/api/v1/turnover/{t['id']}/assign", headers=team["eng1"], json={"housekeeper_id": team["hk1_id"]})
    assert r.status_code == 403
    r = client.post(f"/api/v1/turnover/{t['id']}/assign", headers=team["admin"], json={"housekeeper_id": team["eng1_id"]})
    assert r.status_code == 422


def test_assignment_restrictions(client, team):
    t = open_ticket(client, team)
    r = client.post(f"/api/v1/housekeeping/{t['id']}/start", headers=team["hk2"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "NOT_ASSIGNEE"
    assert client.get(f"/api/v1/turnover/{t['id']}", headers=team["hk2"]).status_code == 403
    assert client.get(f"/api/v1/turnover/{t['id']}", headers=team["eng1"]).status_code == 403  # no repair yet
    r = client.post(f"/api/v1/turnover/{t['id']}/assign", headers=team["admin"],
                    json={"housekeeper_id": team["hk2_id"], "reason": "Shift change"})
    assert r.status_code == 200 and r.json()["assigned_housekeeper"]["id"] == team["hk2_id"]
    assert len(r.json()["assignments"]) == 2
    assert client.post(f"/api/v1/turnover/{t['id']}/start", headers=team["hk1"]).status_code == 403
    assert client.post(f"/api/v1/turnover/{t['id']}/start", headers=team["hk2"]).status_code == 200


def test_invalid_transitions(client, team):
    t = open_ticket(client, team, assign=False)
    # Cannot start before assignment, cannot release before inspections
    assert client.post(f"/api/v1/housekeeping/{t['id']}/start", headers=team["hk1"]).status_code == 403
    r = client.post(f"/api/v1/turnover/{t['id']}/release", headers=team["admin"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "RELEASE_BLOCKED"
    assert any("Housekeeping has not submitted" in b for b in r.json()["error"]["details"])
    client.post(f"/api/v1/turnover/{t['id']}/assign", headers=team["admin"], json={"housekeeper_id": team["hk1_id"]})
    # Cannot save or submit before starting
    r = client.put(f"/api/v1/housekeeping/{t['id']}/checklist", headers=team["hk1"], json={"items": []})
    assert r.status_code == 409
    r = client.post(f"/api/v1/housekeeping/{t['id']}/submit", headers=team["hk1"], json={})
    assert r.status_code == 409
    # Cannot start twice
    assert client.post(f"/api/v1/housekeeping/{t['id']}/start", headers=team["hk1"]).status_code == 200
    assert client.post(f"/api/v1/housekeeping/{t['id']}/start", headers=team["hk1"]).status_code == 409


def test_cancel_ticket_and_out_of_service(client, team):
    t = open_ticket(client, team)
    r = client.post(f"/api/v1/turnover/{t['id']}/cancel", headers=team["admin"],
                    json={"reason": "Flooding", "room_status": "READY_FOR_GUEST"})
    assert r.status_code == 409
    r = client.post(f"/api/v1/turnover/{t['id']}/cancel", headers=team["admin"], json={"reason": "Flooding"})
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert room_status(client, team["admin"], team["room"]) == "OUT_OF_SERVICE"
    r = client.post("/api/v1/turnover", headers=team["admin"], json={"room_id": team["room"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ROOM_OUT_OF_SERVICE"


def test_ticket_list_filters_and_timeline(client, team):
    r2 = make_room(client, team["admin"], "102")
    t1 = open_ticket(client, team)
    open_ticket(client, team, room=r2, assign=False, priority="URGENT")
    page = client.get("/api/v1/turnover?priority=URGENT", headers=team["admin"]).json()
    assert page["total"] == 1
    page = client.get("/api/v1/turnover?status=HOUSEKEEPING_ASSIGNED&status=AWAITING_HOUSEKEEPING", headers=team["admin"]).json()
    assert page["total"] == 2
    assert client.get("/api/v1/turnover?search=102", headers=team["admin"]).json()["total"] == 1
    tl = client.get(f"/api/v1/turnover/{t1['id']}/timeline", headers=team["admin"]).json()
    assert [e["action"] for e in tl] == ["TICKET_CREATED", "TICKET_ASSIGNED"]
