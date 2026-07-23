from pydantic import BaseModel, EmailStr

class UserToken(BaseModel):
    token: str

class AuthorizedUser(BaseModel):
    id: str
    username: str
    is_admin: bool
    email: EmailStr