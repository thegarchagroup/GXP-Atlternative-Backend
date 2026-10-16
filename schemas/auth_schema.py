from pydantic import BaseModel, Field

from models.enums import Department
from schemas.user_schema import UserOut


class LoginRequest(BaseModel):
    department: Department
    user_id: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
    hotel_timezone: str


class MeResponse(BaseModel):
    user: UserOut
    hotel_timezone: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=72)
