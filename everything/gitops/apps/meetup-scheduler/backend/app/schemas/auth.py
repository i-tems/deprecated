from pydantic import BaseModel


class GoogleAuthRequest(BaseModel):
    code: str
    redirect_uri: str


class AuthResponse(BaseModel):
    token: str
    user: "UserResponse"


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    avatar_url: str | None

    class Config:
        from_attributes = True
