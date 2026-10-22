from tests.conftest import engineering_items, housekeeping_round, open_ticket, room_status


def _failed_ticket(client, team, fail=("Air conditioning",)):
    t = open_ticket(client, team)
    detail = housekeeping_round(client, team, t["id"], fail=fail)
    return t["id"], detail["repairs"][0]["id"]


def _start_repair(client, team, repair_id, who="eng1"):
    r = client.post(f"/api/v1/engineering/{repair_id}/assign", headers=team["admin"],
                    json={"engineer_id": team[f"{who}_id"]})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/engineering/{repair_id}/start", headers=team[who])
    assert r.status_code == 200, r.text
    return r.json()


def test_engineering_repair_completion_and_release(client, team):
    ticket_id, repair_id = _failed_ticket(client, team)
    detail = _start_repair(client, team, repair_id)
    assert detail["status"] == "IN_PROGRESS" and detail["failed_items"][0]["item_name"] == "Air conditioning"
    assert room_status(client, team["admin"], team["room"]) == "ENGINEERING_IN_PROGRESS"
    items = engineering_items(client, team["eng1"], repair_id)
    r = client.put(f"/api/v1/engineering/{repair_id}/checklist", headers=team["eng1"],
                   json={"items": items, "diagnosis": "Compressor relay failed", "repair_notes": "Replaced relay"})
    assert r.status_code == 200 and r.json()["session"]["progress"]["percent"] == 100
    r = client.post(f"/api/v1/engineering/{repair_id}/complete", headers=team["eng1"], json={})
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED"
    assert room_status(client, team["admin"], team["room"]) == "AWAITING_FINAL_VERIFICATION"
    # The engineer who did the repair may release (configurable); a different engineer may not
    assert client.post(f"/api/v1/turnover/{ticket_id}/release", headers=team["eng2"]).status_code == 403
    r = client.post(f"/api/v1/turnover/{ticket_id}/release", headers=team["eng1"])
    assert r.status_code == 200 and r.json()["status"] == "CLOSED"
    assert room_status(client, team["admin"], team["room"]) == "READY_FOR_GUEST"
    rep = client.get("/api/v1/reports/maintenance", headers=team["admin"]).json()
    assert rep["total_repairs"] == 1 and rep["top_failed_items"][0]["item_name"] == "Air conditioning"


def test_engineering_failures_prevent_completion(client, team):
    ticket_id, repair_id = _failed_ticket(client, team)
    _start_repair(client, team, repair_id)
    items = engineering_items(client, team["eng1"], repair_id, fail=("Air conditioning operational",))
    r = client.post(f"/api/v1/engineering/{repair_id}/complete", headers=team["eng1"], json={"diagnosis": "Gas leak"})
    assert r.status_code == 422  # nothing filled in yet
    client.put(f"/api/v1/engineering/{repair_id}/checklist", headers=team["eng1"], json={"items": items})
    r = client.post(f"/api/v1/engineering/{repair_id}/complete", headers=team["eng1"],
                    json={"diagnosis": "Gas leak", "repair_notes": "Recharged"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "REPAIR_INCOMPLETE"
    assert any("failed" in d for d in r.json()["error"]["details"])
    # Diagnosis typed so far is kept
    assert client.get(f"/api/v1/engineering/{repair_id}", headers=team["eng1"]).json()["diagnosis"] == "Gas leak"
    assert client.post(f"/api/v1/turnover/{ticket_id}/release", headers=team["admin"]).status_code == 409
    assert room_status(client, team["admin"], team["room"]) == "ENGINEERING_IN_PROGRESS"


def test_reclean_after_repairs(client, team):
    ticket_id, repair_id = _failed_ticket(client, team, fail=("Washbasin",))
    _start_repair(client, team, repair_id)
    items = engineering_items(client, team["eng1"], repair_id)
    r = client.post(f"/api/v1/engineering/{repair_id}/complete",
                    headers=team["eng1"], json={"requires_recleaning": True, "diagnosis": "Cracked basin",
                                                "repair_notes": "Basin replaced"})
    assert r.status_code == 422  # checklist not yet filled
    client.put(f"/api/v1/engineering/{repair_id}/checklist", headers=team["eng1"], json={"items": items})
    r = client.post(f"/api/v1/engineering/{repair_id}/complete", headers=team["eng1"],
                    json={"requires_recleaning": True, "diagnosis": "Cracked basin", "repair_notes": "Basin replaced"})
    assert r.status_code == 200 and r.json()["ticket_status"] == "RECLEAN_REQUIRED"
    assert room_status(client, team["admin"], team["room"]) == "HOUSEKEEPING_ASSIGNED"
    blocked = client.post(f"/api/v1/turnover/{ticket_id}/release", headers=team["admin"])
    assert blocked.status_code == 409 and any("re-clean" in b for b in blocked.json()["error"]["details"])
    pending = client.get("/api/v1/housekeeping/my-tickets?bucket=pending", headers=team["hk1"]).json()
    assert [x["id"] for x in pending] == [ticket_id]
    detail = housekeeping_round(client, team, ticket_id)
    assert detail["status"] == "AWAITING_FINAL_VERIFICATION" and detail["sessions"][-1]["is_reclean"] is True
    r = client.post(f"/api/v1/turnover/{ticket_id}/release", headers=team["admin"])
    assert r.status_code == 200
    assert room_status(client, team["admin"], team["room"]) == "READY_FOR_GUEST"


def test_reclean_finding_new_defect_creates_second_repair(client, team):
    ticket_id, repair_id = _failed_ticket(client, team, fail=("Shower",))
    _start_repair(client, team, repair_id)
    client.put(f"/api/v1/engineering/{repair_id}/checklist", headers=team["eng1"],
               json={"items": engineering_items(client, team["eng1"], repair_id), "diagnosis": "d", "repair_notes": "n"})
    client.post(f"/api/v1/engineering/{repair_id}/complete", headers=team["eng1"], json={"requires_recleaning": True})
    detail = housekeeping_round(client, team, ticket_id, fail=("Drainage",))
    assert detail["status"] == "ENGINEERING_REQUIRED" and len(detail["repairs"]) == 2
    assert not detail["readiness"]["ready"]


def test_self_assignment_and_reopen(client, team):
    ticket_id, repair_id = _failed_ticket(client, team)
    r = client.post(f"/api/v1/engineering/{repair_id}/assign", headers=team["eng1"], json={"engineer_id": team["eng2_id"]})
    assert r.status_code == 403
    r = client.post(f"/api/v1/engineering/{repair_id}/assign", headers=team["eng1"], json={"engineer_id": team["eng1_id"]})
    assert r.status_code == 200 and r.json()["assigned_engineer"]["id"] == team["eng1_id"]
    assert room_status(client, team["admin"], team["room"]) == "ENGINEERING_ASSIGNED"
    r = client.post(f"/api/v1/engineering/{repair_id}/assign", headers=team["eng2"], json={"engineer_id": team["eng2_id"]})
    assert r.status_code == 403
    assert client.post(f"/api/v1/engineering/{repair_id}/start", headers=team["eng2"]).status_code == 403
    client.post(f"/api/v1/engineering/{repair_id}/start", headers=team["eng1"])
    client.put(f"/api/v1/engineering/{repair_id}/checklist", headers=team["eng1"],
               json={"items": engineering_items(client, team["eng1"], repair_id), "diagnosis": "d", "repair_notes": "n"})
    client.post(f"/api/v1/engineering/{repair_id}/complete", headers=team["eng1"], json={})
    assert client.post(f"/api/v1/engineering/{repair_id}/reopen", headers=team["hk1"], json={"reason": "still warm"}).status_code == 403
    r = client.post(f"/api/v1/engineering/{repair_id}/reopen", headers=team["admin"], json={"reason": "Guest reported noise"})
    assert r.status_code == 200 and r.json()["status"] == "REOPENED" and r.json()["reopen_count"] == 1
    assert room_status(client, team["admin"], team["room"]) == "ENGINEERING_ASSIGNED"
    assert client.post(f"/api/v1/turnover/{ticket_id}/release", headers=team["admin"]).status_code == 409
    r = client.post(f"/api/v1/engineering/{repair_id}/start", headers=team["eng1"])
    assert r.status_code == 200 and len(r.json()["sessions"]) == 2
    reopened = client.get("/api/v1/engineering/my-tickets?scope=in_progress", headers=team["eng1"]).json()
    assert reopened["total"] == 1
    dash = client.get("/api/v1/dashboard/engineering", headers=team["eng1"]).json()
    assert dash["in_progress"] == 1


def test_engineering_views_and_notifications(client, team):
    ticket_id, repair_id = _failed_ticket(client, team)
    # Engineers can open the turnover ticket once a repair exists
    assert client.get(f"/api/v1/turnover/{ticket_id}", headers=team["eng2"]).status_code == 200
    notes = client.get("/api/v1/dashboard/notifications", headers=team["eng1"]).json()
    assert any(n["action"] == "REPAIR_CREATED" for n in notes)
    fd = client.get("/api/v1/dashboard/frontdesk", headers=team["admin"]).json()
    assert fd["engineering_required"] == 1 and fd["open_repairs"] == 1
    all_repairs = client.get("/api/v1/engineering/repairs", headers=team["admin"]).json()
    assert all_repairs["total"] == 1
    assert client.get("/api/v1/engineering/repairs", headers=team["eng1"]).status_code == 403


def test_engineering_supervisor_assigns_any_technician(client, team):
    ticket_id, repair_id = _failed_ticket(client, team)
    # supervisor sees every repair and can assign any technician (a technician can only claim for themselves)
    assert client.get("/api/v1/engineering/repairs", headers=team["eng_sup"]).json()["total"] == 1
    assert client.get("/api/v1/engineering/repairs", headers=team["eng1"]).status_code == 403
    r = client.post(f"/api/v1/engineering/{repair_id}/assign", headers=team["eng_sup"], json={"engineer_id": team["eng2_id"]})
    assert r.status_code == 200 and r.json()["assigned_engineer"]["id"] == team["eng2_id"]
    r = client.post(f"/api/v1/engineering/{repair_id}/assign", headers=team["eng_sup"],
                    json={"engineer_id": team["eng1_id"], "reason": "Closer to the room"})
    assert r.status_code == 200 and r.json()["assigned_engineer"]["id"] == team["eng1_id"]
    staff = client.get("/api/v1/dashboard/staff?department=ENGINEERING", headers=team["eng_sup"]).json()
    assert {s["user_id"] for s in staff} == {"eng.sunil", "eng.meera"}  # technicians only, no supervisor
