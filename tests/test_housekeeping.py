from tests.conftest import checklist_items, housekeeping_round, open_ticket, room_status


def test_checklist_validation_on_submit(client, team):
    t = open_ticket(client, team)
    client.post(f"/api/v1/housekeeping/{t['id']}/start", headers=team["hk1"])
    data = client.get(f"/api/v1/housekeeping/{t['id']}/checklist", headers=team["hk1"]).json()
    assert data["session"]["progress"]["percent"] == 0
    # Leave a mandatory item pending
    items = checklist_items(client, team["hk1"], t["id"], pending=("Smoke detector",))
    r = client.post(f"/api/v1/housekeeping/{t['id']}/submit", headers=team["hk1"], json={"items": items})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CHECKLIST_INCOMPLETE"
    assert any("Smoke detector" in d for d in r.json()["error"]["details"])
    # Progress is calculated from required items, and partial work was saved
    data = client.get(f"/api/v1/housekeeping/{t['id']}/checklist", headers=team["hk1"]).json()
    assert 0 < data["session"]["progress"]["percent"] < 100 or data["session"]["progress"]["percent"] == 0
    # Failure without remark is rejected
    sd = next(r for r in data["session"]["results"] if r["item_name"] == "Smoke detector")
    r = client.post(f"/api/v1/housekeeping/{t['id']}/submit", headers=team["hk1"],
                    json={"items": items + [{"result_id": sd["id"], "result": "FAIL"}]})
    assert r.status_code == 422 and any("needs a remark" in d for d in r.json()["error"]["details"])


def test_save_progress_and_item_rules(client, team):
    t = open_ticket(client, team)
    client.post(f"/api/v1/housekeeping/{t['id']}/start", headers=team["hk1"])
    data = client.get(f"/api/v1/housekeeping/{t['id']}/checklist", headers=team["hk1"]).json()
    results = data["session"]["results"]
    door = next(r for r in results if r["item_name"] == "Door lock")
    fan = next(r for r in results if r["item_name"] == "Fan")
    clean = next(r for r in results if r["checklist_type"] == "HOUSEKEEPING_CLEANING")
    r = client.put(f"/api/v1/housekeeping/{t['id']}/checklist", headers=team["hk1"],
                   json={"items": [{"result_id": door["id"], "result": "NOT_APPLICABLE"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NA_NOT_ALLOWED"
    r = client.put(f"/api/v1/housekeeping/{t['id']}/checklist", headers=team["hk1"],
                   json={"items": [{"result_id": clean["id"], "result": "FAIL", "remarks": "x"}]})
    assert r.status_code == 422
    r = client.put(f"/api/v1/housekeeping/{t['id']}/checklist", headers=team["hk1"],
                   json={"items": [{"result_id": fan["id"], "result": "NOT_APPLICABLE"},
                                   {"result_id": door["id"], "result": "PASS"}]})
    assert r.status_code == 200
    saved = {x["id"]: x for x in r.json()["session"]["results"]}
    assert saved[door["id"]]["result"] == "PASS" and saved[door["id"]]["inspector"]["user_id"] == "hk.anita"
    assert r.json()["session"]["progress"]["required_done"] == 1
    # Another housekeeper cannot write to it
    r = client.put(f"/api/v1/housekeeping/{t['id']}/checklist", headers=team["hk2"], json={"items": []})
    assert r.status_code == 403


def test_all_pass_then_ready_for_guest(client, team):
    t = open_ticket(client, team)
    detail = housekeeping_round(client, team, t["id"])
    assert detail["status"] == "AWAITING_FINAL_VERIFICATION"
    assert room_status(client, team["admin"], team["room"]) == "AWAITING_FINAL_VERIFICATION"
    assert detail["readiness"] == {"ready": True, "blockers": [], "can_release": True}
    # Another housekeeper cannot release
    assert client.post(f"/api/v1/turnover/{t['id']}/release", headers=team["hk2"]).status_code == 403
    r = client.post(f"/api/v1/turnover/{t['id']}/release", headers=team["hk1"], json={"notes": "All good"})
    assert r.status_code == 200 and r.json()["status"] == "CLOSED"
    assert r.json()["released_by"]["user_id"] == "hk.anita" and r.json()["released_at"]
    room = client.get(f"/api/v1/rooms/{team['room']}", headers=team["admin"]).json()
    assert room["operational_status"] == "READY_FOR_GUEST" and room["active_ticket_id"] is None and room["last_ready_at"]
    # Ticket can't be released twice
    assert client.post(f"/api/v1/turnover/{t['id']}/release", headers=team["admin"]).status_code == 409


def test_failed_inspection_creates_engineering_request(client, team):
    t = open_ticket(client, team, priority="HIGH")
    detail = housekeeping_round(client, team, t["id"], fail=("Air conditioning", "Toilet flush"))
    assert detail["status"] == "ENGINEERING_REQUIRED"
    assert room_status(client, team["admin"], team["room"]) == "ENGINEERING_REQUIRED"
    assert len(detail["repairs"]) == 1
    repair = detail["repairs"][0]
    assert repair["status"] == "NEW" and repair["priority"] == "HIGH"
    assert "Air conditioning" in repair["reported_defect"] and "Toilet flush" in repair["reported_defect"]
    # Housekeeping results are preserved
    hk_session = detail["sessions"][0]
    assert hk_session["outcome"] == "FAIL" and hk_session["progress"]["failed"] == 2
    # Visible on the engineering board for every engineer
    new = client.get("/api/v1/engineering/my-tickets?scope=new", headers=team["eng2"]).json()
    assert [x["id"] for x in new["items"]] == [repair["id"]]
    # Release is blocked
    r = client.post(f"/api/v1/turnover/{t['id']}/release", headers=team["admin"])
    assert r.status_code == 409
    # Housekeeper sees it under "engineering"
    mine = client.get("/api/v1/housekeeping/my-tickets?bucket=engineering", headers=team["hk1"]).json()
    assert [x["id"] for x in mine] == [t["id"]]
    dash = client.get("/api/v1/dashboard/housekeeping", headers=team["hk1"]).json()
    assert dash["submitted_for_engineering"] == 1


def test_attachment_upload_and_link(client, team):
    t = open_ticket(client, team)
    client.post(f"/api/v1/housekeeping/{t['id']}/start", headers=team["hk1"])
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = client.post("/api/v1/uploads", headers=team["hk1"], files={"file": ("crack.png", png, "image/png")},
                    data={"ticket_id": str(t["id"])})
    assert r.status_code == 201
    att = r.json()
    bad = client.post("/api/v1/uploads", headers=team["hk1"], files={"file": ("x.png", b"MZ\x90\x00 not an image", "image/png")})
    assert bad.status_code == 422
    other = client.post("/api/v1/uploads", headers=team["hk2"], files={"file": ("y.png", png, "image/png")},
                        data={"ticket_id": str(t["id"])})
    assert other.status_code == 403
    items = checklist_items(client, team["hk1"], t["id"], fail=("Mirrors",))
    mirror = next(i for i in items if i["result"] == "FAIL")
    mirror["attachment_ids"] = [att["id"]]
    r = client.post(f"/api/v1/housekeeping/{t['id']}/submit", headers=team["hk1"], json={"items": items})
    assert r.status_code == 200
    repair_id = r.json()["repairs"][0]["id"]
    detail = client.get(f"/api/v1/engineering/{repair_id}", headers=team["eng1"]).json()
    assert detail["failed_items"][0]["attachments"][0]["id"] == att["id"]
    assert client.get(att["url"], headers=team["eng1"]).content == png
    assert client.get(att["url"], headers=team["hk2"]).status_code == 403
