import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    """Base schema for user attributes."""

    email: EmailStr
    full_name: Optional[str] = None
    custom_system_prompt: Optional[str] = None


class UserCreate(BaseModel):
    """Schema for registering a new user."""

    email: EmailStr
    password: str = Field(..., min_length=6, description="Plaintext password")
    full_name: Optional[str] = None
    custom_system_prompt: Optional[str] = None


class UserSettingsUpdate(BaseModel):
    """Schema for updating current user profile and settings."""

    full_name: Optional[str] = None
    custom_system_prompt: Optional[str] = None
    password: Optional[str] = Field(None, min_length=6, description="New plaintext password")


class UserResponse(BaseModel):
    """Public representation of user account."""

    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    custom_system_prompt: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
