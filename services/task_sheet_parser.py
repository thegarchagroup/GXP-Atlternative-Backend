"""Read the property-management system's "Housekeeping Task Sheet" PDF.

Each page is one task sheet (1, 2, ... FLOAT) with a table:
Room No | Room Type | Room Status | FO Status | Reservation Status | Arrival | Departure
and a leading "!" for rooms with an arrival today. Words are placed into columns by their
horizontal position under the header, so multi-word values ("Due Out") stay together.
"""
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pdfplumber

COLUMNS = ["room_number", "room_type", "hk_status", "fo_status", "reservation_status", "arrival", "departure"]
HEADER_WORDS = ["Room", "Room", "Room", "FO", "Reservation", "Arrival", "Departure"]
DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{2}$")
ROOM_RE = re.compile(r"^[A-Za-z0-9-]{1,20}$")


class TaskSheetError(ValueError):
    pass


@dataclass
class SheetRoom:
    room_number: str
    room_type: str = ""
    hk_status: str = ""
    fo_status: str = ""
    reservation_status: str = ""
    arrival: Optional[date] = None
    departure: Optional[date] = None
    arrival_today: bool = False
    sheet_no: str = ""


@dataclass
class ParsedSheet:
    task_date: Optional[date]
    rooms: list = field(default_factory=list)
    pages: int = 0


def _dmy(text: str) -> Optional[date]:
    try:
        return datetime.strptime(text, "%d-%m-%y").date()
    except ValueError:
        return None


def _column_starts(words) -> Optional[list[float]]:
    """x positions of the 7 table columns, from the header line containing 'Arrival' and 'Departure'."""
    arrival = next((w for w in words if w["text"] == "Arrival"), None)
    if not arrival:
        return None
    line = sorted((w for w in words if abs(w["top"] - arrival["top"]) < 3), key=lambda w: w["x0"])
    starts, wanted = [], list(HEADER_WORDS)
    for w in line:
        if wanted and w["text"] == wanted[0]:
            starts.append(w["x0"])
            wanted.pop(0)
    return starts if len(starts) == len(COLUMNS) else None


def parse_task_sheet(data: bytes) -> ParsedSheet:
    if not data.startswith(b"%PDF"):
        raise TaskSheetError("This file is not a PDF.")
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise TaskSheetError("The PDF could not be read.") from exc
    result = ParsedSheet(task_date=None)
    seen = set()
    with pdf:
        result.pages = len(pdf.pages)
        for page in pdf.pages:
            words = page.extract_words(keep_blank_chars=False)
            text = " ".join(w["text"] for w in words)
            m = re.search(r"(\d{2}-\d{2}-\d{2})/[A-Z]+/(\S+)", text)
            sheet_no = m.group(2) if m else ""
            if result.task_date is None:
                d = re.search(r"Task Date From (\d{2}-\d{2}-\d{2})", text)
                result.task_date = _dmy(d.group(1)) if d else (_dmy(m.group(1)) if m else None)
            starts = _column_starts(words)
            if not starts:
                continue
            header_top = next(w["top"] for w in words if w["text"] == "Arrival")
            col = lambda x: max([i for i, s in enumerate(starts) if x >= s - 12] or [-1])  # noqa: E731
            anchors = [w for w in words if w["top"] > header_top + 15 and col(w["x0"]) == 0
                       and ROOM_RE.match(w["text"]) and w["text"] not in ("Filter:", "Room")]
            for a in anchors:
                mid = (a["top"] + a["bottom"]) / 2
                row = [w for w in words if abs((w["top"] + w["bottom"]) / 2 - mid) < 6]
                cells = {c: [] for c in COLUMNS}
                flag = False
                for w in sorted(row, key=lambda w: w["x0"]):
                    i = col(w["x0"])
                    if i < 0:
                        flag = flag or w["text"] == "!"
                    else:
                        cells[COLUMNS[i]].append(w["text"])
                room = " ".join(cells["room_number"])
                # only real table rows: a room number followed by a room type and statuses
                if not cells["room_type"] or not cells["fo_status"] or room in seen:
                    continue
                seen.add(room)
                arr = " ".join(cells["arrival"])
                dep = " ".join(cells["departure"])
                result.rooms.append(SheetRoom(
                    room_number=room, room_type=" ".join(cells["room_type"]), hk_status=" ".join(cells["hk_status"]),
                    fo_status=" ".join(cells["fo_status"]), reservation_status=" ".join(cells["reservation_status"]),
                    arrival=_dmy(arr) if DATE_RE.match(arr) else None,
                    departure=_dmy(dep) if DATE_RE.match(dep) else None,
                    arrival_today=flag, sheet_no=sheet_no,
                ))
    if not result.rooms:
        raise TaskSheetError("No rooms were found. Is this the Housekeeping Task Sheet PDF?")
    return result
