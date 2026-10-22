from fastapi import Depends

from core.dependencies import get_current_user
from core.exceptions import ForbiddenError
from models.enums import Department, Role
from models.user import User


def require_departments(*departments: Department):
    """Dependency factory: allow only users from the listed departments."""
    allowed = set(departments)

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.department not in allowed:
            raise ForbiddenError("Your department does not have access to this resource.")
        return user

    return _checker


def require_roles(*roles: Role):
    """Dependency factory: allow only users with one of the listed roles."""
    allowed = set(roles)

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise ForbiddenError("Your role does not have access to this resource.")
        return user

    return _checker


require_admin = require_departments(Department.FRONT_DESK)
require_user_managers = require_roles(Role.ADMIN, Role.HK_SUPERVISOR, Role.ENG_SUPERVISOR)
require_hk_supervisor = require_roles(Role.HK_SUPERVISOR)
require_eng_supervisor_or_admin = require_roles(Role.ENG_SUPERVISOR, Role.ADMIN)
require_housekeeping = require_departments(Department.HOUSEKEEPING)
require_engineering = require_departments(Department.ENGINEERING)
require_engineering_or_admin = require_departments(Department.ENGINEERING, Department.FRONT_DESK)
require_housekeeping_or_admin = require_departments(Department.HOUSEKEEPING, Department.FRONT_DESK)
require_any = require_departments(Department.FRONT_DESK, Department.HOUSEKEEPING, Department.ENGINEERING)
