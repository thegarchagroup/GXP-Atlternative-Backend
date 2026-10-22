"""Import every model so SQLAlchemy metadata is complete."""
from models.audit import ActivityLog
from models.checklist import ChecklistTemplate, ChecklistTemplateItem
from models.daily_sheet import DailySheet, DailySheetRoom
from models.guest_request import GuestRequest
from models.inspection import Attachment, AttachmentFile, InspectionResult, InspectionSession
from models.repair import RepairRequest
from models.room import Room, RoomType
from models.turnover import TicketAssignment, TurnoverTicket
from models.user import User

__all__ = [
    "ActivityLog", "Attachment", "AttachmentFile", "ChecklistTemplate", "ChecklistTemplateItem", "DailySheet", "DailySheetRoom", "GuestRequest", "InspectionResult",
    "InspectionSession", "RepairRequest", "Room", "RoomType", "TicketAssignment", "TurnoverTicket", "User",
]
