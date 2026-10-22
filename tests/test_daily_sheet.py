"""Daily task sheet: PDF upload, room attendant assignment, runsheet and the simple form."""
import os
from datetime import date

import pytest

from tests.conftest import engineering_items, login, make_user

PDF = open(os.path.join(os.path.dirname(__file__), "fixtures", "daily_report.pdf"), "rb").read()
PNG = b"\x89PNG\r\n\x1a\n" + b"\x02" * 64


def today():
    from services.daily_sheet_service import hotel_today
    return hotel_today()


def upload(client, headers, task_date=None, data=PDF, name="daily_report.pdf"):
    form = {"task_date": task_date.isoformat()} if task_date else {}
    return client.post("/api/v1/housekeeping/daily-sheets/upload", headers=headers,
                       files={"file": (name, data, "application/pdf")}, data=form)


@pytest.fixture
def hk(client, admin):
    """HK supervisor with two room attendants, today's sheet uploaded and its rooms created."""
    from tests.conftest import supervisor
    sup = supervisor(client, admin, "HOUSEKEEPING")
    ra1_id, ra1 = make_user(client, admin, "HOUSEKEEPING", "ra.anita", "Anita")
    ra2_id, ra2 = make_user(client, admin, "HOUSEKEEPING", "ra.ravi", "Ravi")
    tech_id, tech = make_user(client, admin, "ENGINEERING", "tech.sunil", "Sunil")
    sheet = upload(client, sup, today()).json()
    client.post(f"/api/v1/housekeeping/daily-sheets/{sheet['id']}/add-missing-rooms", headers=sup)
    sheet = client.get(f"/api/v1/housekeeping/daily-sheets/by-date/{today()}", headers=sup).json()
    entry = {r["room_number"]: r for r in sheet["rooms"]}
    return {"admin": admin, "sup": sup, "ra1": ra1, "ra1_id": ra1_id, "ra2": ra2, "ra2_id": ra2_id,
            "tech": tech, "tech_id": tech_id, "sheet": sheet, "entry": entry}


def assign(client, hk, numbers, ra="ra1"):
    r = client.post(f"/api/v1/housekeeping/daily-sheets/{hk['sheet']['id']}/assign", headers=hk["sup"],
                    json={"entry_ids": [hk["entry"][n]["id"] for n in numbers], "ra_id": hk[f"{ra}_id"]})
    assert r.status_code == 200, r.text
    return r.json()


def fill(client, headers, entry_id, fail=None, photo=True):
    d = client.get(f"/api/v1/housekeeping/runsheet/{entry_id}", headers=headers).json()
    items = []
    for r in d["session"]["results"]:
        if r["item_name"] == fail:
            item = {"result_id": r["id"], "result": "FAIL", "remarks": f"{fail} not working"}
            if photo:
                att = client.post("/api/v1/uploads", headers=headers, files={"file": ("p.png", PNG, "image/png")}).json()
                item["attachment_ids"] = [att["id"]]
            items.append(item)
        else:
            items.append({"result_id": r["id"], "result": "PASS"})
    return items


def room(client, hk, number):
    return client.get(f"/api/v1/rooms/{hk['entry'][number]['room_id']}", headers=hk["admin"]).json()


# --------------------------------------------------------------------------- upload

def test_upload_reads_every_room_and_the_date(client, admin):
    from tests.conftest import supervisor
    sup = supervisor(client, admin, "HOUSEKEEPING")
    r = upload(client, sup)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["task_date"] == "2026-10-17" and s["rooms_in_file"] == 90 and s["added"] == 90
    assert s["summary"]["total"] == 90 and s["summary"]["arrivals"] == 12 and len(s["summary"]["missing_rooms"]) == 90
    assert s["summary"]["sheet_numbers"] == ["1", "2", "3", "4", "5", "6", "FLOAT"]
    rooms = {x["room_number"]: x for x in s["rooms"]}
    assert rooms["202"]["arrival_today"] is True and rooms["202"]["reservation_status"] == "Departed"
    assert rooms["217"]["reservation_status"] == "Due Out" and rooms["217"]["fo_status"] == "OCC"
    assert rooms["327"]["sheet_no"] == "FLOAT" and rooms["327"]["departure_date"] == "2026-12-31"
    assert rooms["113"]["reservation_status"] == "" and rooms["113"]["arrival_date"] is None
    # kept by date
    assert [x["task_date"] for x in client.get("/api/v1/housekeeping/daily-sheets", headers=sup).json()] == ["2026-10-17"]
    assert client.get("/api/v1/housekeeping/daily-sheets/by-date/2026-10-17", headers=admin).status_code == 200  # front desk can view
    assert client.get("/api/v1/housekeeping/daily-sheets/by-date/2026-10-18", headers=sup).status_code == 404


def test_only_hk_supervisor_uploads_and_bad_files_are_rejected(client, team):
    for h in (team["admin"], team["hk1"], team["eng1"]):
        assert upload(client, h).status_code == 403
    r = upload(client, team["hk_sup"], data=b"not a pdf at all")
    assert r.status_code == 422 and r.json()["error"]["code"] == "TASK_SHEET_UNREADABLE"


def test_add_missing_rooms_creates_rooms_and_types(client, hk):
    assert hk["sheet"]["summary"]["missing_rooms"] == []
    types = {t["name"] for t in client.get("/api/v1/rooms/types", headers=hk["admin"]).json()}
    assert {"GENR", "QUEN", "DKNG", "JSTE", "SUIT", "EDDB", "DOUB", "SNGL", "EKNG"} <= types
    assert room(client, hk, "105")["floor"] == 1 and room(client, hk, "423")["floor"] == 4
    r = room(client, hk, "105")
    assert r["occupancy_status"] == "VACANT" and r["operational_status"] == "AWAITING_HOUSEKEEPING"
    assert room(client, hk, "108")["occupancy_status"] == "OCCUPIED"  # FO status OCC


def test_reupload_keeps_assignments_and_work(client, hk):
    assign(client, hk, ["105", "106"])
    client.post(f"/api/v1/housekeeping/runsheet/{hk['entry']['105']['id']}/start", headers=hk["ra1"])
    r = upload(client, hk["sup"], today()).json()
    assert r["added"] == 0 and r["updated"] == 90 and r["removed"] == 0 and r["upload_count"] == 2
    rooms = {x["room_number"]: x for x in r["rooms"]}
    assert rooms["105"]["status"] == "IN_PROGRESS" and rooms["106"]["assigned_ra"]["user_id"] == "ra.anita"


# --------------------------------------------------------------------------- assignment

def test_assign_by_room_and_by_whole_sheet(client, hk):
    s = assign(client, hk, ["105", "106", "107"])
    assert s["summary"]["unassigned"] == 87
    assert room(client, hk, "105")["operational_status"] == "HOUSEKEEPING_ASSIGNED"
    r = client.post(f"/api/v1/housekeeping/daily-sheets/{hk['sheet']['id']}/assign", headers=hk["sup"],
                    json={"sheet_no": "2", "ra_id": hk["ra2_id"]})
    assert r.status_code == 200
    by_ra = {}
    for x in r.json()["rooms"]:
        if x["assigned_ra"]:
            by_ra.setdefault(x["assigned_ra"]["user_id"], []).append(x["room_number"])
    assert len(by_ra["ra.ravi"]) == 15 and sorted(by_ra["ra.anita"]) == ["105", "106", "107"]
    # unassign
    r = client.post(f"/api/v1/housekeeping/daily-sheets/{hk['sheet']['id']}/assign", headers=hk["sup"],
                    json={"entry_ids": [hk["entry"]["107"]["id"]], "ra_id": None})
    assert r.json()["summary"]["unassigned"] == 73


def test_assignment_rules(client, hk):
    sid = hk["sheet"]["id"]
    one = [hk["entry"]["105"]["id"]]
    r = client.post(f"/api/v1/housekeeping/daily-sheets/{sid}/assign", headers=hk["sup"], json={"entry_ids": one, "ra_id": hk["tech_id"]})
    assert r.status_code == 422  # not a room attendant
    assert client.post(f"/api/v1/housekeeping/daily-sheets/{sid}/assign", headers=hk["ra1"],
                       json={"entry_ids": one, "ra_id": hk["ra1_id"]}).status_code == 403
    assert client.post(f"/api/v1/housekeeping/daily-sheets/{sid}/assign", headers=hk["admin"],
                       json={"entry_ids": one, "ra_id": hk["ra1_id"]}).status_code == 403
    assign(client, hk, ["105"])
    client.post(f"/api/v1/housekeeping/runsheet/{one[0]}/start", headers=hk["ra1"])
    r = client.post(f"/api/v1/housekeeping/daily-sheets/{sid}/assign", headers=hk["sup"], json={"entry_ids": one, "ra_id": hk["ra2_id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ROOM_ALREADY_STARTED"


# --------------------------------------------------------------------------- runsheet

def test_runsheet_priority_order(client, hk):
    # 108 stayover, 217 due out, 105 departed (vacant), 202 arrival today
    assign(client, hk, ["108", "217", "105", "202"])
    order = [x["room_number"] for x in client.get("/api/v1/housekeeping/runsheet", headers=hk["ra1"]).json()]
    assert order == ["202", "105", "217", "108"]
    assert client.get("/api/v1/housekeeping/runsheet", headers=hk["ra2"]).json() == []


def test_all_pass_makes_room_ready(client, hk):
    assign(client, hk, ["105"])
    eid = hk["entry"]["105"]["id"]
    assert client.post(f"/api/v1/housekeeping/runsheet/{eid}/start", headers=hk["ra2"]).status_code == 403
    d = client.post(f"/api/v1/housekeeping/runsheet/{eid}/start", headers=hk["ra1"]).json()
    sections = {r["checklist_type"] for r in d["session"]["results"]}
    assert sections == {"HOUSEKEEPING_CLEANING", "HOUSEKEEPING_INSPECTION"}
    assert room(client, hk, "105")["operational_status"] == "HOUSEKEEPING_IN_PROGRESS"
    r = client.post(f"/api/v1/housekeeping/runsheet/{eid}/finish", headers=hk["ra1"], json={"items": []})
    assert r.status_code == 422 and r.json()["error"]["code"] == "FORM_INCOMPLETE"
    r = client.post(f"/api/v1/housekeeping/runsheet/{eid}/finish", headers=hk["ra1"], json={"items": fill(client, hk["ra1"], eid)})
    assert r.status_code == 200 and r.json()["status"] == "DONE" and r.json()["outcome"] == "PASS"
    rm = room(client, hk, "105")
    assert rm["operational_status"] == "READY_FOR_GUEST" and rm["last_ready_at"]
    s = client.get(f"/api/v1/housekeeping/daily-sheets/by-date/{today()}", headers=hk["sup"]).json()["summary"]
    assert s["done"] == 1 and s["with_issues"] == 0
    notes = client.get("/api/v1/dashboard/notifications", headers=hk["sup"]).json()
    assert any(n["action"] == "ROOM_CLEAN_FINISHED" for n in notes)


def test_failed_item_needs_a_photo_and_goes_to_engineering(client, hk):
    assign(client, hk, ["105"])
    eid = hk["entry"]["105"]["id"]
    client.post(f"/api/v1/housekeeping/runsheet/{eid}/start", headers=hk["ra1"])
    r = client.post(f"/api/v1/housekeeping/runsheet/{eid}/finish", headers=hk["ra1"],
                    json={"items": fill(client, hk["ra1"], eid, fail="Air conditioning", photo=False)})
    assert r.status_code == 422 and any("take a photo" in d for d in r.json()["error"]["details"])
    r = client.post(f"/api/v1/housekeeping/runsheet/{eid}/finish", headers=hk["ra1"],
                    json={"items": fill(client, hk["ra1"], eid, fail="Air conditioning"), "notes": "Smells of burning"})
    assert r.status_code == 200 and r.json()["outcome"] == "FAIL" and len(r.json()["repair_ids"]) == 1
    repair_id = r.json()["repair_ids"][0]
    # vacant room: off sale until engineering fixes it
    assert room(client, hk, "105")["operational_status"] == "ENGINEERING_REQUIRED"
    new = client.get("/api/v1/engineering/my-tickets?scope=new", headers=hk["tech"]).json()["items"]
    assert [x["id"] for x in new] == [repair_id] and new[0]["origin"] == "HOUSEKEEPING"
    detail = client.get(f"/api/v1/engineering/{repair_id}", headers=hk["tech"]).json()
    assert detail["failed_items"][0]["item_name"] == "Air conditioning"
    assert "Smells of burning" in detail["reported_defect"]
    photo = detail["failed_items"][0]["attachments"][0]["url"]
    assert client.get(photo, headers=hk["tech"]).content == PNG
    assert client.get(photo, headers=hk["sup"]).content == PNG
    # technician fixes it -> room ready again
    client.post(f"/api/v1/engineering/{repair_id}/assign", headers=hk["tech"], json={"engineer_id": hk["tech_id"]})
    client.post(f"/api/v1/engineering/{repair_id}/start", headers=hk["tech"])
    client.put(f"/api/v1/engineering/{repair_id}/checklist", headers=hk["tech"],
               json={"items": engineering_items(client, hk["tech"], repair_id), "diagnosis": "Fan motor", "repair_notes": "Replaced"})
    assert client.post(f"/api/v1/engineering/{repair_id}/complete", headers=hk["tech"], json={}).status_code == 200
    assert room(client, hk, "105")["operational_status"] == "READY_FOR_GUEST"


def test_failure_in_occupied_room_keeps_guest_in(client, hk):
    assign(client, hk, ["108"])  # stayover, OCC
    eid = hk["entry"]["108"]["id"]
    client.post(f"/api/v1/housekeeping/runsheet/{eid}/start", headers=hk["ra1"])
    r = client.post(f"/api/v1/housekeeping/runsheet/{eid}/finish", headers=hk["ra1"],
                    json={"items": fill(client, hk["ra1"], eid, fail="Television")})
    assert r.status_code == 200
    rm = room(client, hk, "108")
    assert rm["occupancy_status"] == "OCCUPIED" and rm["operational_status"] == "READY_FOR_GUEST" and rm["open_repairs"] == 1


def test_arrival_room_repair_is_high_priority(client, hk):
    assign(client, hk, ["202"])
    eid = hk["entry"]["202"]["id"]
    client.post(f"/api/v1/housekeeping/runsheet/{eid}/start", headers=hk["ra1"])
    r = client.post(f"/api/v1/housekeeping/runsheet/{eid}/finish", headers=hk["ra1"],
                    json={"items": fill(client, hk["ra1"], eid, fail="Shower")}).json()
    rep = client.get(f"/api/v1/engineering/{r['repair_ids'][0]}", headers=hk["tech"]).json()
    assert rep["priority"] == "HIGH"


def test_past_date_sheet_does_not_change_live_rooms(client, hk):
    before = room(client, hk, "105")
    upload(client, hk["sup"], date(2026, 1, 1))  # an old sheet
    after = room(client, hk, "105")
    assert after["operational_status"] == before["operational_status"]
    assert len(client.get("/api/v1/housekeeping/daily-sheets", headers=hk["sup"]).json()) == 2


def test_room_not_set_up_cannot_start(client, admin):
    from tests.conftest import supervisor
    sup = supervisor(client, admin, "HOUSEKEEPING")
    ra_id, ra = make_user(client, admin, "HOUSEKEEPING", "ra.one")
    s = upload(client, sup, today()).json()
    e = next(x for x in s["rooms"] if x["room_number"] == "105")
    client.post(f"/api/v1/housekeeping/daily-sheets/{s['id']}/assign", headers=sup, json={"entry_ids": [e["id"]], "ra_id": ra_id})
    r = client.post(f"/api/v1/housekeeping/runsheet/{e['id']}/start", headers=ra)
    assert r.status_code == 409 and r.json()["error"]["code"] == "ROOM_NOT_SET_UP"


def test_sheet_with_another_date_is_visible_once_moved_to_today(client, admin):
    """The reported problem: a PDF dated another day is filed under that day, so the RA's
    runsheet for today is empty. The RA can see which dates have rooms, and the supervisor
    can move the sheet to today without losing assignments."""
    from tests.conftest import supervisor
    sup = supervisor(client, admin, "HOUSEKEEPING")
    ra_id, ra = make_user(client, admin, "HOUSEKEEPING", "ra.anita")
    s = upload(client, sup).json()  # dated 17 Oct 2026 by the PDF
    assert s["task_date"] == "2026-10-17"
    e = next(x for x in s["rooms"] if x["room_number"] == "105")
    client.post(f"/api/v1/housekeeping/daily-sheets/{s['id']}/assign", headers=sup, json={"entry_ids": [e["id"]], "ra_id": ra_id})
    if today() != date(2026, 10, 17):
        assert client.get("/api/v1/housekeeping/runsheet", headers=ra).json() == []
    dates = client.get("/api/v1/housekeeping/runsheet/dates", headers=ra).json()
    assert dates["dates"] == [{"task_date": "2026-10-17", "rooms": 1, "done": 0}]
    assert [x["room_number"] for x in client.get("/api/v1/housekeeping/runsheet?task_date=2026-10-17", headers=ra).json()] == ["105"]
    # supervisor moves it to today: the assignment comes along and the RA sees it
    moved = client.post(f"/api/v1/housekeeping/daily-sheets/{s['id']}/move", headers=sup, json={"task_date": today().isoformat()})
    assert moved.status_code == 200 and moved.json()["task_date"] == today().isoformat()
    assert [x["room_number"] for x in client.get("/api/v1/housekeeping/runsheet", headers=ra).json()] == ["105"]
    # can't move onto a date that already has a sheet; only the supervisor can move
    other = upload(client, sup, date(2026, 1, 1)).json()
    r = client.post(f"/api/v1/housekeeping/daily-sheets/{other['id']}/move", headers=sup, json={"task_date": today().isoformat()})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SHEET_DATE_TAKEN"
    assert client.post(f"/api/v1/housekeeping/daily-sheets/{s['id']}/move", headers=ra, json={"task_date": "2026-01-02"}).status_code == 403
