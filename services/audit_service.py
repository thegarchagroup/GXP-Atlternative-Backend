from typing import Optional

from sqlalchemy.orm import Session

from models.audit import ActivityLog


def log(db: Session, *, actor, action: str, message: str, entity_type: str, entity_id: Optional[int] = None,
        ticket_id: Optional[int] = None, repair_id: Optional[int] = None, room_id: Optional[int] = None,
        from_status=None, to_status=None, details: Optional[dict] = None) -> ActivityLog:
    """Add an audit entry to the current transaction (committed with the change it describes)."""
    entry = ActivityLog(
        action=action,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
        ticket_id=ticket_id,
        repair_id=repair_id,
        room_id=room_id,
        actor_id=actor.id if actor is not None else None,
        from_status=str(from_status) if from_status is not None else None,
        to_status=str(to_status) if to_status is not None else None,
        details=details,
    )
    db.add(entry)
    return entry
