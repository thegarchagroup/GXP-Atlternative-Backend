from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.permissions import require_admin
from database.connection import get_db
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
