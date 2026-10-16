from tests.conftest import make_room, room_type_id


def test_room_creation_and_updates(client, admin):
    rid = make_room(client, admin, "204", floor=2)
    r = client.get(f"/api/v1/rooms/{rid}", headers=admin).json()
    assert r["operational_status"] == "READY_FOR_GUEST" and r["occupancy_status"] == "VACANT"
    r = client.post("/api/v1/rooms", headers=admin, json={"room_number": "204", "floor": 2,
                                                          "room_type_id": room_type_id(client, admin)})
    assert r.status_code == 409
    r = client.put(f"/api/v1/rooms/{rid}", headers=admin, json={"floor": 3, "room_type_id": room_type_id(client, admin, "Suite")})
    assert r.status_code == 200 and r.json()["floor"] == 3 and r.json()["room_type"]["name"] == "Suite"


def test_room_list_filters_and_pagination(client, admin):
    for n, f in [("101", 1), ("102", 1), ("201", 2)]:
        make_room(client, admin, n, floor=f)
    page = client.get("/api/v1/rooms?floor=1&page_size=1", headers=admin).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert client.get("/api/v1/rooms?search=20", headers=admin).json()["total"] == 1
    assert client.get("/api/v1/rooms?operational_status=READY_FOR_GUEST", headers=admin).json()["total"] == 3


def test_occupancy_requires_ready_room(client, admin):
    rid = make_room(client, admin, "301", floor=3)
    r = client.patch(f"/api/v1/rooms/{rid}/occupancy", headers=admin, json={"occupancy_status": "OCCUPIED"})
    assert r.status_code == 200 and r.json()["occupancy_status"] == "OCCUPIED"
    client.patch(f"/api/v1/rooms/{rid}/occupancy", headers=admin, json={"occupancy_status": "VACANT"})
    client.patch(f"/api/v1/rooms/{rid}/status", headers=admin, json={"operational_status": "OUT_OF_SERVICE", "reason": "Leak"})
    r = client.patch(f"/api/v1/rooms/{rid}/occupancy", headers=admin, json={"occupancy_status": "OCCUPIED"})
    assert r.status_code == 409


def test_status_override_rules(client, admin):
    rid = make_room(client, admin, "401", floor=4)
    r = client.patch(f"/api/v1/rooms/{rid}/status", headers=admin,
                     json={"operational_status": "ENGINEERING_IN_PROGRESS", "reason": "test"})
    assert r.status_code == 409
    client.post("/api/v1/turnover", headers=admin, json={"room_id": rid})
    r = client.patch(f"/api/v1/rooms/{rid}/status", headers=admin,
                     json={"operational_status": "READY_FOR_GUEST", "reason": "skip cleaning"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ROOM_IN_WORKFLOW"


def test_room_history_and_type_management(client, admin):
    rid = make_room(client, admin, "501", floor=5)
    client.post("/api/v1/turnover", headers=admin, json={"room_id": rid})
    h = client.get(f"/api/v1/rooms/{rid}/history", headers=admin).json()
    assert len(h["tickets"]) == 1 and any(a["action"] == "TICKET_CREATED" for a in h["activity"])
    r = client.post("/api/v1/rooms/types", headers=admin, json={"name": "Accessible", "category": "Guest room"})
    assert r.status_code == 201
    r = client.put(f"/api/v1/rooms/types/{r.json()['id']}", headers=admin, json={"is_active": False})
    assert r.json()["is_active"] is False


def test_ready_for_guest_count_excludes_occupied_rooms(client, admin):
    a = make_room(client, admin, "601", floor=6)
    make_room(client, admin, "602", floor=6)
    client.patch(f"/api/v1/rooms/{a}/occupancy", headers=admin, json={"occupancy_status": "OCCUPIED"})
    fd = client.get("/api/v1/dashboard/frontdesk", headers=admin).json()
    assert fd["total_rooms"] == 2 and fd["occupied"] == 1 and fd["ready_for_guest"] == 1
