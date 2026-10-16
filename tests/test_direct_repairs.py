"""Front desk raising engineering repairs directly (not from a housekeeping inspection)."""
from tests.conftest import engineering_items, housekeeping_round, make_room, open_ticket


def raise_repair(client, team, room=None, engineer=None, defect="AC not cooling, guest complaint", priority="HIGH"):
    body = {"room_id": room or team["room"], "reported_defect": defect, "priority": priority}
    if engineer:
        body["engineer_id"] = team[f"{engineer}_id"]
    r = client.post("/api/v1/engineering/repairs", headers=team["admin"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def room(client, team, room_id=None):
    return client.get(f"/api/v1/rooms/{room_id or team['room']}", headers=team["admin"]).json()


def finish(client, team, repair_id, who="eng1", reclean=False):
    if client.get(f"/api/v1/engineering/{repair_id}", headers=team[who]).json()["status"] in ("NEW",):
        client.post(f"/api/v1/engineering/{repair_id}/assign", headers=team["admin"], json={"engineer_id": team[f"{who}_id"]})
    r = client.post(f"/api/v1/engineering/{repair_id}/start", headers=team[who])
    assert r.status_code == 200, r.text
    client.put(f"/api/v1/engineering/{repair_id}/checklist", headers=team[who],
               json={"items": engineering_items(client, team[who], repair_id), "diagnosis": "Faulty part", "repair_notes": "Replaced"})
    r = client.post(f"/api/v1/engineering/{repair_id}/complete", headers=team[who], json={"requires_recleaning": reclean})
    assert r.status_code == 200, r.text
    return r.json()


def test_only_front_desk_can_raise(client, team):
    body = {"room_id": team["room"], "reported_defect": "Leaking tap"}
    assert client.post("/api/v1/engineering/repairs", headers=team["hk1"], json=body).status_code == 403
    assert client.post("/api/v1/engineering/repairs", headers=team["eng1"], json=body).status_code == 403
    r = client.post("/api/v1/engineering/repairs", headers=team["admin"], json={"room_id": team["room"], "reported_defect": "x"})
    assert r.status_code == 422


def test_vacant_ready_room_is_blocked_then_ready_again(client, team):
    rep = raise_repair(client, team)
    assert rep["origin"] == "FRONT_DESK" and rep["ticket_id"] is None and rep["blocks_room"] is True
    assert rep["status"] == "NEW" and rep["priority"] == "HIGH"
    assert room(client, team)["operational_status"] == "ENGINEERING_REQUIRED"
    # can't be sold while blocked
    r = client.patch(f"/api/v1/rooms/{team['room']}/occupancy", headers=team["admin"], json={"occupancy_status": "OCCUPIED"})
    assert r.status_code == 409
    fd = client.get("/api/v1/dashboard/frontdesk", headers=team["admin"]).json()
    assert fd["ready_for_guest"] == 0 and fd["engineering_required"] == 1
    # visible to engineers as a new request
    new = client.get("/api/v1/engineering/my-tickets?scope=new", headers=team["eng2"]).json()
    assert [x["id"] for x in new["items"]] == [rep["id"]]
    client.post(f"/api/v1/engineering/{rep['id']}/assign", headers=team["eng1"], json={"engineer_id": team["eng1_id"]})
    r = room(client, team)
    assert r["operational_status"] == "ENGINEERING_ASSIGNED" and r["assigned_engineer"]["id"] == team["eng1_id"]
    client.post(f"/api/v1/engineering/{rep['id']}/start", headers=team["eng1"])
    assert room(client, team)["operational_status"] == "ENGINEERING_IN_PROGRESS"
    client.put(f"/api/v1/engineering/{rep['id']}/checklist", headers=team["eng1"],
               json={"items": engineering_items(client, team["eng1"], rep["id"]), "diagnosis": "Low gas", "repair_notes": "Recharged"})
    r = client.post(f"/api/v1/engineering/{rep['id']}/complete", headers=team["eng1"], json={})
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED"
    after = room(client, team)
    assert after["operational_status"] == "READY_FOR_GUEST" and after["assigned_engineer"] is None
    assert after["last_ready_at"] and after["open_repairs"] == 0
    assert client.patch(f"/api/v1/rooms/{team['room']}/occupancy", headers=team["admin"],
                        json={"occupancy_status": "OCCUPIED"}).status_code == 200


def test_occupied_room_stays_occupied(client, team):
    client.patch(f"/api/v1/rooms/{team['room']}/occupancy", headers=team["admin"], json={"occupancy_status": "OCCUPIED"})
    rep = raise_repair(client, team, engineer="eng1")
    assert rep["blocks_room"] is False and rep["status"] == "ASSIGNED" and rep["room_occupancy"] == "OCCUPIED"
    r = room(client, team)
    assert r["occupancy_status"] == "OCCUPIED" and r["operational_status"] == "READY_FOR_GUEST"
    assert r["open_repairs"] == 1 and r["assigned_engineer"]["id"] == team["eng1_id"]
    finish(client, team, rep["id"])
    r = room(client, team)
    assert r["occupancy_status"] == "OCCUPIED" and r["operational_status"] == "READY_FOR_GUEST" and r["open_repairs"] == 0


def test_room_in_turnover_gets_repair_attached(client, team):
    t = open_ticket(client, team)
    housekeeping_round(client, team, t["id"])  # all passed -> awaiting final verification
    rep = raise_repair(client, team, defect="Guest left note: shower drains slowly")
    assert rep["ticket_id"] == t["id"] and rep["blocks_room"] is False
    ticket = client.get(f"/api/v1/turnover/{t['id']}", headers=team["admin"]).json()
    assert ticket["status"] == "ENGINEERING_REQUIRED" and not ticket["readiness"]["ready"]
    assert client.post(f"/api/v1/turnover/{t['id']}/release", headers=team["admin"]).status_code == 409
    finish(client, team, rep["id"])
    ticket = client.get(f"/api/v1/turnover/{t['id']}", headers=team["admin"]).json()
    assert ticket["status"] == "AWAITING_FINAL_VERIFICATION" and ticket["readiness"]["ready"] is True
    assert client.post(f"/api/v1/turnover/{t['id']}/release", headers=team["admin"]).status_code == 200


def test_repair_raised_before_housekeeping_does_not_skip_housekeeping(client, team):
    t = open_ticket(client, team)  # housekeeping assigned, not started
    rep = raise_repair(client, team, engineer="eng1")
    finish(client, team, rep["id"])
    ticket = client.get(f"/api/v1/turnover/{t['id']}", headers=team["admin"]).json()
    assert ticket["status"] == "HOUSEKEEPING_ASSIGNED"  # still needs cleaning and inspection
    detail = housekeeping_round(client, team, t["id"])
    assert detail["status"] == "AWAITING_FINAL_VERIFICATION" and detail["readiness"]["ready"] is True


def test_checkout_attaches_open_repair_to_turnover(client, team):
    client.patch(f"/api/v1/rooms/{team['room']}/occupancy", headers=team["admin"], json={"occupancy_status": "OCCUPIED"})
    rep = raise_repair(client, team, engineer="eng1")
    client.post(f"/api/v1/engineering/{rep['id']}/start", headers=team["eng1"])  # work started while guest in room
    t = open_ticket(client, team)  # guest checks out
    detail = client.get(f"/api/v1/engineering/{rep['id']}", headers=team["admin"]).json()
    assert detail["ticket_id"] == t["id"] and detail["blocks_room"] is False
    tl = [e["action"] for e in client.get(f"/api/v1/turnover/{t['id']}/timeline", headers=team["admin"]).json()]
    assert "REPAIR_ATTACHED" in tl
    after_hk = housekeeping_round(client, team, t["id"])
    assert after_hk["status"] == "ENGINEERING_IN_PROGRESS" and not after_hk["readiness"]["ready"]
    client.put(f"/api/v1/engineering/{rep['id']}/checklist", headers=team["eng1"],
               json={"items": engineering_items(client, team["eng1"], rep["id"]), "diagnosis": "d", "repair_notes": "n"})
    assert client.post(f"/api/v1/engineering/{rep['id']}/complete", headers=team["eng1"], json={}).status_code == 200
    ticket = client.get(f"/api/v1/turnover/{t['id']}", headers=team["admin"]).json()
    assert ticket["readiness"]["ready"] is True, ticket["readiness"]
    assert client.post(f"/api/v1/turnover/{t['id']}/release", headers=team["admin"]).status_code == 200


def test_reclean_after_direct_repair_opens_turnover(client, team):
    rep = raise_repair(client, team, engineer="eng1")
    finish(client, team, rep["id"], reclean=True)
    r = room(client, team)
    assert r["operational_status"] == "AWAITING_HOUSEKEEPING" and r["active_ticket_id"]
    ticket = client.get(f"/api/v1/turnover/{r['active_ticket_id']}", headers=team["admin"]).json()
    assert ticket["status"] == "AWAITING_HOUSEKEEPING" and "Re-clean after repair" in (ticket["notes"] or "")


def test_reopen_direct_repair_blocks_again(client, team):
    rep = raise_repair(client, team, engineer="eng1")
    finish(client, team, rep["id"])
    assert room(client, team)["operational_status"] == "READY_FOR_GUEST"
    r = client.post(f"/api/v1/engineering/{rep['id']}/reopen", headers=team["admin"], json={"reason": "Still noisy"})
    assert r.status_code == 200 and r.json()["status"] == "REOPENED"
    assert room(client, team)["operational_status"] == "ENGINEERING_ASSIGNED"
    finish(client, team, rep["id"])
    assert room(client, team)["operational_status"] == "READY_FOR_GUEST"


def test_direct_repair_photos_notifications_and_reports(client, team):
    rep = raise_repair(client, team, engineer="eng1")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    up = client.post("/api/v1/uploads", headers=team["eng1"], files={"file": ("a.png", png, "image/png")},
                     data={"repair_id": str(rep["id"])})
    assert up.status_code == 201
    assert client.post("/api/v1/uploads", headers=team["eng2"], files={"file": ("b.png", png, "image/png")},
                       data={"repair_id": str(rep["id"])}).status_code == 403
    assert client.get(up.json()["url"], headers=team["eng2"]).status_code == 200
    notes = client.get("/api/v1/dashboard/notifications", headers=team["eng1"]).json()
    assert any(n["action"] == "REPAIR_RAISED" for n in notes)
    m = client.get("/api/v1/reports/maintenance", headers=team["admin"]).json()
    assert m["total_repairs"] == 1 and m["rows"][0]["origin"] == "FRONT_DESK" and m["rows"][0]["ticket_number"] is None
    # housekeeping can't see a direct repair that isn't part of their ticket
    assert client.get(f"/api/v1/engineering/{rep['id']}", headers=team["hk1"]).status_code == 403
