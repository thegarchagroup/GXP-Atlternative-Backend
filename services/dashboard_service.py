from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.guest_request import GuestRequest
from models.enums import OPEN_REQUEST_STATUSES, OPEN_REPAIR_STATUSES, OccupancyStatus, OperationalStatus, RepairStatus, TicketStatus
from models.repair import RepairRequest
from models.room import Room
from models.turnover import TurnoverTicket
from models.user import User
from schemas.dashboard_schema import EngineeringSummary, FrontDeskSummary, HousekeepingSummary
from services.housekeeping_service import BUCKETS


def frontdesk(db: Session) -> FrontDeskSummary:
    active = Room.is_active.is_(True)
    by_op = dict(db.execute(select(Room.operational_status, func.count(Room.id)).where(active)
                            .group_by(Room.operational_status)).all())
    by_occ = dict(db.execute(select(Room.occupancy_status, func.count(Room.id)).where(active)
                             .group_by(Room.occupancy_status)).all())
    ready_vacant = db.scalar(select(func.count(Room.id)).where(
        active, Room.operational_status == OperationalStatus.READY_FOR_GUEST,
        Room.occupancy_status == OccupancyStatus.VACANT)) or 0
    open_tickets = db.scalar(select(func.count(TurnoverTicket.id)).where(TurnoverTicket.is_active.is_(True))) or 0
    open_repairs = db.scalar(select(func.count(RepairRequest.id))
                             .where(RepairRequest.status.in_(list(OPEN_REPAIR_STATUSES)))) or 0

    def op(s):
        return by_op.get(s, 0)

    return FrontDeskSummary(
        total_rooms=sum(by_op.values()),
        occupied=by_occ.get(OccupancyStatus.OCCUPIED, 0),
        vacant=by_occ.get(OccupancyStatus.VACANT, 0),
        ready_for_guest=ready_vacant,  # sellable rooms: ready and nobody in them
        awaiting_housekeeping=op(OperationalStatus.AWAITING_HOUSEKEEPING),
        housekeeping_assigned=op(OperationalStatus.HOUSEKEEPING_ASSIGNED),
        housekeeping_in_progress=op(OperationalStatus.HOUSEKEEPING_IN_PROGRESS),
        engineering_required=op(OperationalStatus.ENGINEERING_REQUIRED),
        engineering_assigned=op(OperationalStatus.ENGINEERING_ASSIGNED),
        engineering_in_progress=op(OperationalStatus.ENGINEERING_IN_PROGRESS),
        awaiting_final_verification=op(OperationalStatus.AWAITING_FINAL_VERIFICATION),
        out_of_service=op(OperationalStatus.OUT_OF_SERVICE),
        open_tickets=open_tickets,
        open_repairs=open_repairs,
        pending_repairs=db.scalar(select(func.count(RepairRequest.id)).where(RepairRequest.status == RepairStatus.PENDING)) or 0,
        open_requests=db.scalar(select(func.count(GuestRequest.id)).where(GuestRequest.status.in_(list(OPEN_REQUEST_STATUSES))))
        or 0,
    )


def housekeeping(db: Session, user: User) -> HousekeepingSummary:
    rows = dict(db.execute(select(TurnoverTicket.status, func.count(TurnoverTicket.id))
                           .where(TurnoverTicket.assigned_housekeeper_id == user.id)
                           .group_by(TurnoverTicket.status)).all())

    def total(statuses):
        return sum(rows.get(s, 0) for s in statuses)

    return HousekeepingSummary(
        assigned=total([s for s in TicketStatus if s not in (TicketStatus.CLOSED, TicketStatus.CANCELLED)]),
        pending=total(BUCKETS["pending"]),
        in_progress=total(BUCKETS["in_progress"]),
        submitted_for_engineering=total(BUCKETS["engineering"]),
        completed=total(BUCKETS["completed"]),
    )


def engineering(db: Session, user: User) -> EngineeringSummary:
    mine = dict(db.execute(select(RepairRequest.status, func.count(RepairRequest.id))
                           .where(RepairRequest.assigned_engineer_id == user.id)
                           .group_by(RepairRequest.status)).all())
    new = db.scalar(select(func.count(RepairRequest.id)).where(
        RepairRequest.assigned_engineer_id.is_(None), RepairRequest.status.in_(list(OPEN_REPAIR_STATUSES)))) or 0
    awaiting = db.scalar(select(func.count(RepairRequest.id))
                         .join(TurnoverTicket, TurnoverTicket.id == RepairRequest.ticket_id)
                         .where(RepairRequest.assigned_engineer_id == user.id,
                                RepairRequest.status == RepairStatus.COMPLETED,
                                TurnoverTicket.is_active.is_(True))) or 0
    return EngineeringSummary(
        new_requests=new,
        assigned=mine.get(RepairStatus.ASSIGNED, 0),
        in_progress=mine.get(RepairStatus.IN_PROGRESS, 0),
        awaiting_verification=awaiting,
        completed=mine.get(RepairStatus.COMPLETED, 0),
        reopened=mine.get(RepairStatus.REOPENED, 0),
        pending=mine.get(RepairStatus.PENDING, 0),
    )
