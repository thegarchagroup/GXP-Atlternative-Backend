from tests.conftest import make_room, open_ticket, room_type_id


def test_checklist_crud_admin_only(client, team):
    r = client.post("/api/v1/checklists", headers=team["hk1"], json={"name": "X", "checklist_type": "HOUSEKEEPING_INSPECTION"})
    assert r.status_code == 403
    r = client.post("/api/v1/checklists", headers=team["admin"], json={"name": "X", "checklist_type": "HOUSEKEEPING_INSPECTION"})
    assert r.status_code == 403  # front desk no longer edits the form
    r = client.post("/api/v1/checklists", headers=team["hk_sup"], json={"name": "Balcony", "checklist_type": "HOUSEKEEPING_INSPECTION"})
    assert r.status_code == 201 and r.json()["department"] == "HOUSEKEEPING"
    cid = r.json()["id"]
    r = client.post(f"/api/v1/checklists/{cid}/items", headers=team["hk_sup"],
                    json={"name": "Balcony door", "category": "Balcony", "allow_not_applicable": True, "display_order": 5})
    assert r.status_code == 201
    item_id = r.json()["id"]
    assert client.put(f"/api/v1/checklists/items/{item_id}", headers=team["eng1"], json={"name": "x"}).status_code == 403
    r = client.put(f"/api/v1/checklists/items/{item_id}", headers=team["hk_sup"], json={"is_mandatory": False})
    assert r.json()["is_mandatory"] is False
    r = client.put(f"/api/v1/checklists/items/{item_id}", headers=team["hk_sup"], json={"room_type_ids": [9999]})
    assert r.status_code == 422
    lists = client.get("/api/v1/checklists?checklist_type=HOUSEKEEPING_INSPECTION", headers=team["hk1"]).json()
    assert {c["name"] for c in lists} >= {"Engineering items", "Balcony"}
    assert client.delete(f"/api/v1/checklists/items/{item_id}", headers=team["hk_sup"]).status_code == 200
    assert client.delete(f"/api/v1/checklists/{cid}", headers=team["hk_sup"]).status_code == 200
    assert client.get(f"/api/v1/checklists/{cid}", headers=team["admin"]).status_code == 404


def test_checklist_changes_preserve_history(client, team):
    t = open_ticket(client, team)
    client.post(f"/api/v1/housekeeping/{t['id']}/start", headers=team["hk1"])
    before = client.get(f"/api/v1/housekeeping/{t['id']}/checklist", headers=team["hk1"]).json()["session"]["results"]
    tv = next(r for r in before if r["item_name"] == "Television")

    templates = client.get("/api/v1/checklists?checklist_type=HOUSEKEEPING_INSPECTION", headers=team["admin"]).json()
    tpl = templates[0]
    tv_item = next(i for i in tpl["items"] if i["name"] == "Television")
    client.put(f"/api/v1/checklists/items/{tv_item['id']}", headers=team["hk_sup"], json={"name": "Smart TV and casting"})
    client.post(f"/api/v1/checklists/{tpl['id']}/items", headers=team["hk_sup"], json={"name": "Coffee machine"})
    door = next(i for i in tpl["items"] if i["name"] == "Door closer")
    client.delete(f"/api/v1/checklists/items/{door['id']}", headers=team["hk_sup"])

    after = client.get(f"/api/v1/housekeeping/{t['id']}/checklist", headers=team["hk1"]).json()["session"]["results"]
    names = {r["item_name"] for r in after}
    assert "Television" in names and "Door closer" in names
    assert "Smart TV and casting" not in names and "Coffee machine" not in names
    assert len(after) == len(before) and next(r for r in after if r["id"] == tv["id"])["item_name"] == "Television"

    # A new inspection picks up the changes
    room2 = make_room(client, team["admin"], "202", floor=2)
    t2 = open_ticket(client, team, room=room2)
    client.post(f"/api/v1/housekeeping/{t2['id']}/start", headers=team["hk1"])
    new = {r["item_name"] for r in
           client.get(f"/api/v1/housekeeping/{t2['id']}/checklist", headers=team["hk1"]).json()["session"]["results"]}
    assert {"Smart TV and casting", "Coffee machine"} <= new and "Door closer" not in new


def test_room_type_applicability(client, team):
    suite = room_type_id(client, team["admin"], "Suite")
    tpl = client.get("/api/v1/checklists?checklist_type=HOUSEKEEPING_INSPECTION", headers=team["admin"]).json()[0]
    client.post(f"/api/v1/checklists/{tpl['id']}/items", headers=team["hk_sup"],
                json={"name": "Living room sofa", "room_type_ids": [suite]})
    preview_std = client.get(f"/api/v1/checklists/preview?room_type_id={room_type_id(client, team['admin'])}",
                             headers=team["admin"]).json()
    preview_suite = client.get(f"/api/v1/checklists/preview?room_type_id={suite}", headers=team["admin"]).json()
    assert "Living room sofa" not in {i["name"] for i in preview_std}
    assert "Living room sofa" in {i["name"] for i in preview_suite}


def test_no_active_checklist_blocks_start(client, team):
    for tpl in client.get("/api/v1/checklists", headers=team["admin"]).json():
        if tpl["department"] == "HOUSEKEEPING":
            client.put(f"/api/v1/checklists/{tpl['id']}", headers=team["hk_sup"], json={"is_active": False})
    t = open_ticket(client, team)
    r = client.post(f"/api/v1/housekeeping/{t['id']}/start", headers=team["hk1"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_CHECKLIST"


def test_reports_room_turnover(client, team):
    open_ticket(client, team)
    rep = client.get("/api/v1/reports/room-turnover", headers=team["admin"]).json()
    assert rep["total_tickets"] == 1 and rep["open"] == 1 and rep["rows"][0]["created_at"].endswith("Z")
    assert client.get("/api/v1/reports/room-turnover", headers=team["hk1"]).status_code == 403
