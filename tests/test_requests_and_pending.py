"""Stage 3: front desk guest requests, and "not doable now" repairs with the pending tracker."""
from datetime import date, timedelta

from tests.conftest import engineering_items, housekeeping_round, make_room, open_ticket


# --------------------------------------------------------------------------- guest requests

def _request(client, team, text="Water bottle please", priority="HIGH", room=None):
    r = client.post("/api/v1/requests", headers=team["admin"], json={"room_id": room or team["room"], "description": text, "priority": priority})
    assert r.status_code == 201, r.text
    return r.json()


def test_guest_request_full_flow(client, team):
    req = _request(client, team)
    assert req["status"] == "NEW" and req["request_number"].startswith("GR-") and req["room_number"] == "101"
    # only front desk creates
    assert client.post("/api/v1/requests", headers=team["hk_sup"], json={"room_id": team["room"], "description": "x y"}).status_code == 403
    # supervisor sees it and assigns a room attendant (not a technician)
    assert [r["id"] for r in client.get("/api/v1/requests", headers=team["hk_sup"]).json()] == [req["id"]]
    assert client.post(f"/api/v1/requests/{req['id']}/assign", headers=team["hk_sup"], json={"ra_id": team["eng1_id"]}).status_code == 422
    assert client.post(f"/api/v1/requests/{req['id']}/assign", headers=team["admin"], json={"ra_id": team["hk1_id"]}).status_code == 403
    r = client.post(f"/api/v1/requests/{req['id']}/assign", headers=team["hk_sup"], json={"ra_id": team["hk1_id"]})
    assert r.status_code == 200 and r.json()["status"] == "ASSIGNED" and r.json()["assigned_ra"]["id"] == team["hk1_id"]
    # the room attendant sees only theirs, starts and completes it
    assert client.get("/api/v1/requests", headers=team["hk2"]).json() == []
    assert [x["id"] for x in client.get("/api/v1/requests", headers=team["hk1"]).json()] == [req["id"]]
    assert client.post(f"/api/v1/requests/{req['id']}/start", headers=team["hk2"]).status_code == 403
    assert client.post(f"/api/v1/requests/{req['id']}/start", headers=team["hk1"]).json()["status"] == "IN_PROGRESS"
    # can't be reassigned once started
    assert client.post(f"/api/v1/requests/{req['id']}/assign", headers=team["hk_sup"], json={"ra_id": team["hk2_id"]}).status_code == 409
    done = client.post(f"/api/v1/requests/{req['id']}/done", headers=team["hk1"], json={"note": "Left 2 bottles"}).json()
    assert done["status"] == "DONE" and done["completion_note"] == "Left 2 bottles" and done["minutes_to_complete"] is not None
    assert done["created_at"] and done["assigned_at"] and done["started_at"] and done["completed_at"]
    # front desk sees the outcome, and the notifications reach each party
    fd = client.get("/api/v1/requests", headers=team["admin"]).json()[0]
    assert fd["status"] == "DONE"
    assert any(n["action"] == "REQUEST_DONE" for n in client.get("/api/v1/dashboard/notifications", headers=team["admin"]).json())
    assert any(n["action"] == "REQUEST_CREATED" for n in client.get("/api/v1/dashboard/notifications", headers=team["hk_sup"]).json())
    assert any(n["action"] == "REQUEST_ASSIGNED" for n in client.get("/api/v1/dashboard/notifications", headers=team["hk1"]).json())


def test_request_done_directly_cancel_and_filters(client, team):
    a = _request(client, team, "Extra pillow", "NORMAL")
    b = _request(client, team, "Iron and board", "LOW")
    client.post(f"/api/v1/requests/{a['id']}/assign", headers=team["hk_sup"], json={"ra_id": team["hk1_id"]})
    assert client.post(f"/api/v1/requests/{a['id']}/done", headers=team["hk1"], json={}).json()["status"] == "DONE"
    assert client.post(f"/api/v1/requests/{a['id']}/cancel", headers=team["admin"], json={"reason": "Guest left"}).status_code == 409
    r = client.post(f"/api/v1/requests/{b['id']}/cancel", headers=team["admin"], json={"reason": "Guest changed mind"})
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    open_ = client.get("/api/v1/requests?status=NEW&status=ASSIGNED&status=IN_PROGRESS", headers=team["admin"]).json()
    assert open_ == []
    assert client.get("/api/v1/dashboard/frontdesk", headers=team["admin"]).json()["open_requests"] == 0


# --------------------------------------------------------------------------- not doable now

def _repair_in_progress(client, team, fail=("Air conditioning",)):
    t = open_ticket(client, team)
    rep = housekeeping_round(client, team, t["id"], fail=fail)["repairs"][0]["id"]
    client.post(f"/api/v1/engineering/{rep}/assign", headers=team["eng_sup"], json={"engineer_id": team["eng1_id"]})
    client.post(f"/api/v1/engineering/{rep}/start", headers=team["eng1"])
    return t["id"], rep


def _direct_repair(client, team, room=None, engineer="eng1"):
    r = client.post("/api/v1/engineering/repairs", headers=team["admin"],
                    json={"room_id": room or team["room"], "reported_defect": "Safe will not lock", "engineer_id": team[f"{engineer}_id"]})
    return r.json()["id"]


def test_not_doable_now_and_resume(client, team):
    tid, rep = _repair_in_progress(client, team)
    body = {"reason": "NEEDS_PARTS", "note": "Compressor capacitor on order", "expected_date": (date.today() + timedelta(days=3)).isoformat(),
            "room_sellable": False}
    assert client.post(f"/api/v1/engineering/{rep}/pending", headers=team["eng2"], json=body).status_code == 403
    r = client.post(f"/api/v1/engineering/{rep}/pending", headers=team["eng1"], json=body)
    assert r.status_code == 200 and r.json()["status"] == "PENDING" and r.json()["pending_reason"] == "NEEDS_PARTS"
    # it can't be completed while pending, and the turnover can't be released
    assert client.post(f"/api/v1/engineering/{rep}/complete", headers=team["eng1"], json={}).status_code == 409
    assert client.post(f"/api/v1/turnover/{tid}/release", headers=team["admin"]).status_code == 409
    # tracker: supervisor and front desk see it; the technician sees their own
    pend = client.get("/api/v1/engineering/pending", headers=team["eng_sup"]).json()
    assert [x["id"] for x in pend] == [rep] and pend[0]["days_pending"] == 0 and pend[0]["overdue"] is False
    assert [x["id"] for x in client.get("/api/v1/engineering/pending", headers=team["admin"]).json()] == [rep]
    assert client.get("/api/v1/engineering/pending", headers=team["eng2"]).json() == []
    assert client.get("/api/v1/engineering/pending", headers=team["hk1"]).status_code == 403
    assert client.get("/api/v1/engineering/my-tickets?scope=pending", headers=team["eng1"]).json()["total"] == 1
    assert client.get("/api/v1/dashboard/engineering", headers=team["eng1"]).json()["pending"] == 1
    # resume and fix it
    r = client.post(f"/api/v1/engineering/{rep}/resume", headers=team["eng1"])
    assert r.status_code == 200 and r.json()["status"] == "IN_PROGRESS"
    client.put(f"/api/v1/engineering/{rep}/checklist", headers=team["eng1"],
               json={"items": engineering_items(client, team["eng1"], rep), "diagnosis": "Capacitor", "repair_notes": "Fitted new part"})
    assert client.post(f"/api/v1/engineering/{rep}/complete", headers=team["eng1"], json={}).json()["status"] == "COMPLETED"
    assert client.get("/api/v1/engineering/pending", headers=team["eng_sup"]).json() == []


def test_pending_room_sellable_or_not(client, team):
    # vacant ready room, direct repair: blocked until done...
    rep = _direct_repair(client, team)
    room = lambda: client.get(f"/api/v1/rooms/{team['room']}", headers=team["admin"]).json()  # noqa: E731
    assert room()["operational_status"] == "ENGINEERING_ASSIGNED"
    client.post(f"/api/v1/engineering/{rep}/start", headers=team["eng1"])
    # ...but if it can still be sold while waiting for the part, the room is ready again
    client.post(f"/api/v1/engineering/{rep}/pending", headers=team["eng1"],
                json={"reason": "NEEDS_VENDOR", "note": "Safe supplier visiting Friday", "room_sellable": True})
    assert room()["operational_status"] == "READY_FOR_GUEST" and room()["open_repairs"] == 1
    # a second room that can't be sold stays blocked
    r2 = make_room(client, team["admin"], "102")
    rep2 = _direct_repair(client, team, room=r2)
    client.post(f"/api/v1/engineering/{rep2}/start", headers=team["eng1"])
    client.post(f"/api/v1/engineering/{rep2}/pending", headers=team["eng1"],
                json={"reason": "NEEDS_VACANT_ROOM", "note": "Ceiling leak, needs two days", "room_sellable": False})
    assert client.get(f"/api/v1/rooms/{r2}", headers=team["admin"]).json()["operational_status"] != "READY_FOR_GUEST"


def test_tracker_actions_reassign_reschedule_escalate_cancel(client, team):
    rep = _direct_repair(client, team)
    client.post(f"/api/v1/engineering/{rep}/start", headers=team["eng1"])
    client.post(f"/api/v1/engineering/{rep}/pending", headers=team["eng1"],
                json={"reason": "NEEDS_PARTS", "note": "Lock motor", "expected_date": (date.today() - timedelta(days=1)).isoformat()})
    p = client.get("/api/v1/engineering/pending", headers=team["eng_sup"]).json()[0]
    assert p["overdue"] is True
    # reschedule
    r = client.post(f"/api/v1/engineering/{rep}/reschedule", headers=team["eng_sup"],
                    json={"expected_date": (date.today() + timedelta(days=2)).isoformat(), "note": "Supplier delayed"})
    assert r.status_code == 200 and r.json()["overdue"] is False and "Supplier delayed" in r.json()["pending_note"]
    # escalate: urgent; only supervisors / front desk
    assert client.post(f"/api/v1/engineering/{rep}/escalate", headers=team["eng1"], json={"note": "VIP"}).status_code == 403
    r = client.post(f"/api/v1/engineering/{rep}/escalate", headers=team["admin"], json={"note": "VIP arriving tomorrow"})
    assert r.json()["priority"] == "URGENT" and r.json()["escalated"] is True
    # reassign keeps it pending; the new technician resumes
    r = client.post(f"/api/v1/engineering/{rep}/assign", headers=team["eng_sup"], json={"engineer_id": team["eng2_id"]})
    assert r.json()["status"] == "PENDING" and r.json()["assigned_engineer"]["id"] == team["eng2_id"]
    assert client.post(f"/api/v1/engineering/{rep}/resume", headers=team["eng1"]).status_code == 403
    assert client.post(f"/api/v1/engineering/{rep}/resume", headers=team["eng2"]).json()["status"] == "IN_PROGRESS"
    # cancel
    assert client.post(f"/api/v1/engineering/{rep}/cancel", headers=team["eng2"], json={"note": "no"}).status_code == 403
    r = client.post(f"/api/v1/engineering/{rep}/cancel", headers=team["eng_sup"], json={"note": "Lock replaced under warranty"})
    assert r.json()["status"] == "CANCELLED"
    assert client.get(f"/api/v1/rooms/{team['room']}", headers=team["admin"]).json()["operational_status"] == "READY_FOR_GUEST"
    tl = [e["action"] for e in client.get("/api/v1/dashboard/notifications?include_own=true&limit=50", headers=team["admin"]).json()]
    for a in ("REPAIR_PENDING", "REPAIR_RESCHEDULED", "REPAIR_ESCALATED", "REPAIR_RESUMED", "REPAIR_CANCELLED"):
        assert a in tl, a
