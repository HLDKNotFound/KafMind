import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class FileResponse(BaseModel):
    """Public representation of an uploaded file."""

    id: uuid.UUID
    user_id: uuid.UUID
    filename: str
    file_path: str
    file_size: int
    mime_type: str
    status: str
    chunk_count: int
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FileUploadAcceptedResponse(BaseModel):
    """Response returned upon 202 Accepted file upload."""

    message: str = "File upload accepted and queued for processing"
    file: FileResponse
    file_id: uuid.UUID


class FileDeleteResponse(BaseModel):
    """Response returned upon successful file deletion."""

    message: str = "File deleted successfully"
    file_id: uuid.UUID


class FileStatusEvent(BaseModel):
    """Event model broadcasted via Redis Pub/Sub and SSE."""

    file_id: str
    status: str
    chunk_count: int = 0
    error: Optional[str] = None
