from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ChatSessionCreate(BaseModel):
    """Schema for creating a new chat session."""

    title: Optional[str] = Field(default="New Chat", max_length=255)


class ChatSessionUpdate(BaseModel):
    """Schema for updating an existing chat session title."""

    title: str = Field(min_length=1, max_length=255)


class ChatSessionResponse(BaseModel):
    """Schema representing chat session metadata."""

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatMessageResponse(BaseModel):
    """Schema representing a chat message."""

    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    sources: Optional[List[Dict[str, Any]]] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatStreamRequest(BaseModel):
    """Schema for streaming message requests."""

    message: str = Field(min_length=1, description="User's query or conversational message")
    selected_file_ids: Optional[List[str]] = Field(
        default=None,
        description="Optional list of specific file UUIDs to restrict document search to",
    )
