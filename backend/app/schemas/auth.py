from typing import Optional

from pydantic import BaseModel, EmailStr

from app.schemas.user import UserResponse


class LoginRequest(BaseModel):
    """Schema for user login credentials."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Schema for access and refresh tokens returned upon login or token refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: Optional[UserResponse] = None


class RefreshTokenRequest(BaseModel):
    """Schema for requesting a new access token via refresh token."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """Optional schema for logout request providing refresh token to invalidate."""

    refresh_token: Optional[str] = None


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str
