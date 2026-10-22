from enum import Enum


class StrEnum(str, Enum):
    """Same behaviour as Python 3.11's enum.StrEnum (works on Python 3.10):
    members are strings, and str()/format() give the plain value."""

    def __str__(self) -> str:
        return str(self.value)

    def __format__(self, format_spec: str) -> str:
        return format(str(self.value), format_spec)


class Department(StrEnum):
    FRONT_DESK = "FRONT_DESK"
    HOUSEKEEPING = "HOUSEKEEPING"
    ENGINEERING = "ENGINEERING"


class Role(StrEnum):
    ADMIN = "ADMIN"                       # Front Desk
    HK_SUPERVISOR = "HK_SUPERVISOR"       # Housekeeping
    ROOM_ATTENDANT = "ROOM_ATTENDANT"     # Housekeeping
    ENG_SUPERVISOR = "ENG_SUPERVISOR"     # Engineering
    TECHNICIAN = "TECHNICIAN"             # Engineering


ROLE_DEPARTMENT = {
    Role.ADMIN: Department.FRONT_DESK,
    Role.HK_SUPERVISOR: Department.HOUSEKEEPING,
    Role.ROOM_ATTENDANT: Department.HOUSEKEEPING,
    Role.ENG_SUPERVISOR: Department.ENGINEERING,
    Role.TECHNICIAN: Department.ENGINEERING,
}

# Role given to existing accounts that only had a department
DEFAULT_ROLE = {
    Department.FRONT_DESK: Role.ADMIN,
    Department.HOUSEKEEPING: Role.ROOM_ATTENDANT,
    Department.ENGINEERING: Role.TECHNICIAN,
}

# Who may create, edit, deactivate and delete which accounts
MANAGEABLE_ROLES = {
    Role.ADMIN: {Role.ADMIN, Role.HK_SUPERVISOR, Role.ENG_SUPERVISOR},
    Role.HK_SUPERVISOR: {Role.ROOM_ATTENDANT},
    Role.ENG_SUPERVISOR: {Role.TECHNICIAN},
}

SUPERVISOR_ROLES = {Role.HK_SUPERVISOR, Role.ENG_SUPERVISOR}


class OccupancyStatus(StrEnum):
    OCCUPIED = "OCCUPIED"
    VACANT = "VACANT"


class OperationalStatus(StrEnum):
    READY_FOR_GUEST = "READY_FOR_GUEST"
    AWAITING_HOUSEKEEPING = "AWAITING_HOUSEKEEPING"
    HOUSEKEEPING_ASSIGNED = "HOUSEKEEPING_ASSIGNED"
    HOUSEKEEPING_IN_PROGRESS = "HOUSEKEEPING_IN_PROGRESS"
    ENGINEERING_REQUIRED = "ENGINEERING_REQUIRED"
    ENGINEERING_ASSIGNED = "ENGINEERING_ASSIGNED"
    ENGINEERING_IN_PROGRESS = "ENGINEERING_IN_PROGRESS"
    AWAITING_FINAL_VERIFICATION = "AWAITING_FINAL_VERIFICATION"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class TicketStatus(StrEnum):
    AWAITING_HOUSEKEEPING = "AWAITING_HOUSEKEEPING"
    HOUSEKEEPING_ASSIGNED = "HOUSEKEEPING_ASSIGNED"
    HOUSEKEEPING_IN_PROGRESS = "HOUSEKEEPING_IN_PROGRESS"
    ENGINEERING_REQUIRED = "ENGINEERING_REQUIRED"
    ENGINEERING_ASSIGNED = "ENGINEERING_ASSIGNED"
    ENGINEERING_IN_PROGRESS = "ENGINEERING_IN_PROGRESS"
    RECLEAN_REQUIRED = "RECLEAN_REQUIRED"
    AWAITING_FINAL_VERIFICATION = "AWAITING_FINAL_VERIFICATION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


TERMINAL_TICKET_STATUSES = {TicketStatus.CLOSED, TicketStatus.CANCELLED}


class RepairStatus(StrEnum):
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REOPENED = "REOPENED"
    CANCELLED = "CANCELLED"


OPEN_REPAIR_STATUSES = {RepairStatus.NEW, RepairStatus.ASSIGNED, RepairStatus.IN_PROGRESS, RepairStatus.REOPENED}


class Priority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class ChecklistType(StrEnum):
    HOUSEKEEPING_CLEANING = "HOUSEKEEPING_CLEANING"
    HOUSEKEEPING_INSPECTION = "HOUSEKEEPING_INSPECTION"
    ENGINEERING_INSPECTION = "ENGINEERING_INSPECTION"


CHECKLIST_DEPARTMENT = {
    ChecklistType.HOUSEKEEPING_CLEANING: Department.HOUSEKEEPING,
    ChecklistType.HOUSEKEEPING_INSPECTION: Department.HOUSEKEEPING,
    ChecklistType.ENGINEERING_INSPECTION: Department.ENGINEERING,
}


class SessionKind(StrEnum):
    HOUSEKEEPING = "HOUSEKEEPING"
    ENGINEERING = "ENGINEERING"


class SessionStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"


class SessionOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class ItemResult(StrEnum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
