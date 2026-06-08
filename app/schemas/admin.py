from pydantic import BaseModel


class UserAdminUpdateRequest(BaseModel):
    is_admin: bool
