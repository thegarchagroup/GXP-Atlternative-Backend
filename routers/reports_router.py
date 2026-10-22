from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from core.permissions import require_admin, require_roles
from database.connection import get_db
from models.enums import Role
from models.user import User
from schemas.common import _iso_utc
from services import report_service

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])


def _serialise(report: dict) -> dict:
    for row in report["rows"]:
        for key, value in list(row.items()):
            if hasattr(value, "isoformat") and key.endswith("_at"):
                row[key] = _iso_utc(value)
    return report


@router.get("/export/{report}")
def operational_report(report: Literal["daily-runsheet", "ra-productivity", "engineering-issues", "guest-requests"],
                       date_from: Optional[date] = None, date_to: Optional[date] = None, day: Optional[date] = None,
                       format: Literal["json", "csv", "xlsx"] = Query("json"),
                       user: User = Depends(require_roles(Role.ADMIN, Role.HK_SUPERVISOR, Role.ENG_SUPERVISOR)),
                       db: Session = Depends(get_db)):
    """Operational reports, with times in the hotel timezone.
    - daily-runsheet (day): every room on a day's task sheet, its room attendant and timings
    - ra-productivity (date_from, date_to): per room attendant
    - engineering-issues (date_from, date_to): repairs, including pending ageing
    - guest-requests (date_from, date_to): requests and turnaround
    format=json for the screen, csv or xlsx to download."""
    from services import export_report_service as svc
    rep = svc.build(db, user, report, date_from, date_to, day)
    if format == "json":
        return rep
    if format == "csv":
        return Response(svc.to_csv(rep), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{rep["filename"]}.csv"'})
    return Response(svc.to_xlsx(rep), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{rep["filename"]}.xlsx"'})


@router.get("/room-turnover")
def room_turnover(date_from: Optional[date] = None, date_to: Optional[date] = None,
                  _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Tickets opened in the date range (default: last 30 days) with turnaround times."""
    return _serialise(report_service.room_turnover(db, date_from, date_to))


@router.get("/maintenance")
def maintenance(date_from: Optional[date] = None, date_to: Optional[date] = None,
                _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Repair requests in the date range, repair times and most frequently failed items."""
    return _serialise(report_service.maintenance(db, date_from, date_to))
