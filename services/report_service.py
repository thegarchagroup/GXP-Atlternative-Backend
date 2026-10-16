from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.enums import ItemResult, RepairStatus, SessionKind, TicketStatus
from models.inspection import InspectionResult, InspectionSession
from models.repair import RepairRequest
from models.turnover import TurnoverTicket


def _range(date_from: Optional[date], date_to: Optional[date]) -> tuple[datetime, datetime, date, date]:
    date_to = date_to or date.today()
    date_from = date_from or (date_to - timedelta(days=30))
    return datetime.combine(date_from, time.min), datetime.combine(date_to + timedelta(days=1), time.min), date_from, date_to


def _minutes(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if a and b:
        return round((b - a).total_seconds() / 60, 1)
    return None


def _avg(values) -> Optional[float]:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def room_turnover(db: Session, date_from: Optional[date], date_to: Optional[date]) -> dict:
    start, end, f, t = _range(date_from, date_to)
    tickets = list(db.scalars(select(TurnoverTicket).where(TurnoverTicket.created_at >= start, TurnoverTicket.created_at < end)
                              .order_by(TurnoverTicket.created_at.desc())).unique().all())
    rows = []
    for tk in tickets:
        rows.append({
            "ticket_id": tk.id,
            "ticket_number": tk.ticket_number,
            "room_number": tk.room.room_number,
            "floor": tk.room.floor,
            "status": tk.status.value,
            "priority": tk.priority.value,
            "housekeeper": tk.assigned_housekeeper.display_name if tk.assigned_housekeeper else None,
            "created_at": tk.created_at,
            "released_at": tk.released_at,
            "housekeeping_minutes": _minutes(tk.housekeeping_started_at, tk.housekeeping_completed_at),
            "turnaround_minutes": _minutes(tk.created_at, tk.released_at),
            "repairs": len(tk.repairs),
            "is_exception": tk.is_exception,
        })
    by_status = Counter(r["status"] for r in rows)
    return {
        "date_from": f.isoformat(),
        "date_to": t.isoformat(),
        "total_tickets": len(rows),
        "closed": by_status.get(TicketStatus.CLOSED.value, 0),
        "cancelled": by_status.get(TicketStatus.CANCELLED.value, 0),
        "open": sum(1 for tk in tickets if tk.is_active),
        "with_repairs": sum(1 for r in rows if r["repairs"]),
        "avg_turnaround_minutes": _avg(r["turnaround_minutes"] for r in rows),
        "avg_housekeeping_minutes": _avg(r["housekeeping_minutes"] for r in rows),
        "by_status": dict(by_status),
        "rows": rows[:500],
    }


def maintenance(db: Session, date_from: Optional[date], date_to: Optional[date]) -> dict:
    start, end, f, t = _range(date_from, date_to)
    repairs = list(db.scalars(select(RepairRequest).where(RepairRequest.created_at >= start, RepairRequest.created_at < end)
                              .order_by(RepairRequest.created_at.desc())).unique().all())
    failed = db.execute(
        select(InspectionResult.item_name, InspectionResult.category)
        .join(InspectionSession, InspectionSession.id == InspectionResult.session_id)
        .where(InspectionSession.kind == SessionKind.HOUSEKEEPING, InspectionResult.result == ItemResult.FAIL,
               InspectionSession.submitted_at >= start, InspectionSession.submitted_at < end)
    ).all()
    top = Counter((n, c) for n, c in failed).most_common(10)
    rows = [{
        "repair_id": r.id,
        "repair_number": r.repair_number,
        "ticket_number": r.ticket.ticket_number if r.ticket else None,
        "origin": r.origin,
        "room_number": r.room.room_number,
        "status": r.status.value,
        "priority": r.priority.value,
        "engineer": r.assigned_engineer.display_name if r.assigned_engineer else None,
        "reported_defect": r.reported_defect,
        "created_at": r.created_at,
        "completed_at": r.completed_at,
        "repair_minutes": _minutes(r.started_at, r.completed_at),
        "reopen_count": r.reopen_count,
        "requires_recleaning": r.requires_recleaning,
    } for r in repairs]
    return {
        "date_from": f.isoformat(),
        "date_to": t.isoformat(),
        "total_repairs": len(rows),
        "completed": sum(1 for r in repairs if r.status == RepairStatus.COMPLETED),
        "open": sum(1 for r in repairs if r.status not in (RepairStatus.COMPLETED, RepairStatus.CANCELLED)),
        "reopened": sum(1 for r in repairs if r.reopen_count > 0),
        "required_recleaning": sum(1 for r in repairs if r.requires_recleaning),
        "avg_repair_minutes": _avg(r["repair_minutes"] for r in rows),
        "top_failed_items": [{"item_name": n, "category": c, "count": k} for (n, c), k in top],
        "rows": rows[:500],
    }
