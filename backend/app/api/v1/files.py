import asyncio
import json
import logging
from pathlib import Path
from typing import List, Optional
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.config import get_settings
from app.core.database import get_db
from app.core.redis import get_redis_client
from app.core.security import decode_token, get_current_user, is_token_blacklisted
from app.models.file import DocumentFile, FileStatus
from app.models.user import User
from app.schemas.file import (
    FileDeleteResponse,
    FileResponse,
    FileUploadAcceptedResponse,
)
from app.services.kafka_producer import publish_file_uploaded
from app.services.qdrant_service import delete_vectors_by_file_id

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


async def get_current_user_sse(
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency supporting both Authorization header and query param for SSE connections."""
    auth_header = request.headers.get("Authorization")
    raw_token = None
    if auth_header and auth_header.startswith("Bearer "):
        raw_token = auth_header.split(" ", 1)[1]
    elif token:
        raw_token = token

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(raw_token)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jti = payload.get("jti")
    if jti and await is_token_blacklisted(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed user identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=FileUploadAcceptedResponse,
)
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Upload document file, store to disk, persist PENDING record, and publish Kafka event."""
    # 1. Validate file extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed formats: PDF, DOCX, TXT, MD",
        )

    # 2. Prepare upload destination
    file_id = uuid.uuid4()
    upload_dir = Path(settings.UPLOAD_DIR) / str(current_user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / f"{file_id}_{file.filename}"

    # 3. Stream file to disk with chunked reading and size validation to prevent OOM
    max_size_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    total_size = 0
    chunk_size = 1024 * 1024  # 1MB chunk

    try:
        with open(destination, "wb") as f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > max_size_bytes:
                    f.close()
                    if destination.is_file():
                        destination.unlink()
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File size exceeds maximum allowed limit of {settings.MAX_UPLOAD_SIZE_MB}MB",
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        if destination.is_file():
            destination.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store file: {str(e)}",
        )

    if total_size == 0:
        if destination.is_file():
            destination.unlink()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    # 4. Create PENDING DB record
    doc_file = DocumentFile(
        id=file_id,
        user_id=current_user.id,
        filename=file.filename or "unknown",
        file_path=str(destination.resolve()),
        file_size=total_size,
        mime_type=file.content_type or "application/octet-stream",
        status=FileStatus.PENDING.value,
        chunk_count=0,
    )

    db.add(doc_file)
    await db.commit()
    await db.refresh(doc_file)

    # 5. Publish event to Kafka
    await publish_file_uploaded(
        file_id=doc_file.id,
        user_id=current_user.id,
        file_path=doc_file.file_path,
        filename=doc_file.filename,
    )

    # 6. Immediately return 202 Accepted
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "message": "File upload accepted and queued for processing",
            "file_id": str(doc_file.id),
            "file": {
                "id": str(doc_file.id),
                "user_id": str(doc_file.user_id),
                "filename": doc_file.filename,
                "file_path": doc_file.file_path,
                "file_size": doc_file.file_size,
                "mime_type": doc_file.mime_type,
                "status": doc_file.status,
                "chunk_count": doc_file.chunk_count,
                "error_message": doc_file.error_message,
                "created_at": doc_file.created_at.isoformat(),
            },
        },
    )


@router.get("", response_model=List[FileResponse])
async def list_files(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[FileResponse]:
    """Retrieve list of files uploaded by the authenticated user."""
    stmt = (
        select(DocumentFile)
        .where(DocumentFile.user_id == current_user.id)
        .order_by(DocumentFile.created_at.desc())
    )
    result = await db.execute(stmt)
    files = result.scalars().all()
    return [FileResponse.model_validate(f) for f in files]


@router.delete("/{file_id}", response_model=FileDeleteResponse)
async def delete_file(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileDeleteResponse:
    """Delete file record, remove vector index in Qdrant, and delete physical file."""
    stmt = select(DocumentFile).where(
        DocumentFile.id == file_id,
        DocumentFile.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    doc_file = result.scalar_one_or_none()

    if doc_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    # 1. Delete vector embeddings from Qdrant
    try:
        await delete_vectors_by_file_id(file_id)
    except Exception as e:
        logger.warning(f"Error deleting vectors for file {file_id}: {e}")

    # 2. Delete physical file from disk
    file_path = Path(doc_file.file_path)
    if file_path.is_file():
        try:
            await asyncio.to_thread(file_path.unlink)
        except Exception as e:
            logger.warning(f"Failed to remove file from disk {file_path}: {e}")

    # 3. Delete database record
    await db.delete(doc_file)
    await db.commit()

    return FileDeleteResponse(
        message="File deleted successfully",
        file_id=file_id,
    )


@router.get("/status-stream")
async def file_status_stream(
    request: Request,
    current_user: User = Depends(get_current_user_sse),
    max_events: Optional[int] = Query(None, description="Optional max events before closing stream"),
):
    """Server-Sent Events (SSE) streaming real-time status from Redis Pub/Sub."""
    channel_name = f"file_status:{current_user.id}"
    redis = get_redis_client()
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel_name)

    async def event_generator():
        event_count = 0
        try:
            # Yield initial connection confirmation
            yield {
                "event": "connected",
                "data": json.dumps({
                    "message": "Connected to file status stream",
                    "user_id": str(current_user.id),
                }),
            }
            event_count += 1
            if max_events is not None and event_count >= max_events:
                return

            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=0.5,
                )
                if message and message.get("type") == "message":
                    data = message.get("data")
                    yield {
                        "event": "status",
                        "data": data if isinstance(data, str) else json.dumps(data),
                    }
                    event_count += 1
                    if max_events is not None and event_count >= max_events:
                        break
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await pubsub.unsubscribe(channel_name)
                await pubsub.aclose()
            except Exception:
                pass

    return EventSourceResponse(event_generator())
