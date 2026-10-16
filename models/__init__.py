"""Import every model so SQLAlchemy metadata is complete."""
from models.audit import ActivityLog
from models.checklist import ChecklistTemplate, ChecklistTemplateItem
from models.inspection import Attachment, InspectionResult, InspectionSession
from models.repair import RepairRequest
from models.room import Room, RoomType
from models.turnover import TicketAssignment, TurnoverTicket
from models.user import User

__all__ = [
    "ActivityLog", "Attachment", "ChecklistTemplate", "ChecklistTemplateItem", "InspectionResult",
    "InspectionSession", "RepairRequest", "Room", "RoomType", "TicketAssignment", "TurnoverTicket", "User",
]
